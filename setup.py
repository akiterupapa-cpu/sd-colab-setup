# ============================================================
# Stable Diffusion WebUI (Colab) セットアップ本体
#
# ★正本。ここを直せば、全員が次回の起動から自動で最新になる。
#   生徒さんのノートブックを貼り替える必要はない。
#
# 置き場所: https://github.com/akiterupapa-cpu/sd-colab-setup
# 呼び出し元: ノートブックの1セル目（notebook_cell.py 参照）
# ============================================================
SETUP_VERSION = '2026-09-17a'

import os, re, shutil, threading, json, subprocess, time

# ★これを消してはいけない（2026-08-19c で復活させた）
#   Colab は MPLBACKEND に 'module://matplotlib_inline.backend_inline' を入れており、
#   これがそのまま venv 側の python に引き継がれると、matplotlib が
#   「そんなバックエンドは無い」と ValueError を投げて launch.py が起動前に死ぬ。
#   元のコードに最初から入っていた1行を、整理のつもりで削ったのが原因だった。
import matplotlib
matplotlib.use('Agg')
os.environ['MPLBACKEND'] = 'Agg'

from google.colab import drive, runtime

print('=' * 54)
print(f'  Stable Diffusion セットアップ　版：{SETUP_VERSION}')
print('=' * 54)


def _opt(name, default):
    """ノートブック側で設定された値を読む。無ければ既定値を使う。
    ★古いノートブックから呼ばれても落ちないように、必ず既定値を持たせること。"""
    return globals().get(name, default)


def sh(cmd, cwd=None, quiet=False):
    """シェルコマンドを実行し、出力をそのまま画面に流す。
    ノートブックの「!コマンド」の代わり（この本体は普通のPythonとして書く）。"""
    # ★PYTHONUNBUFFERED を必ず付ける。パイプで受けると子プロセス側が
    #   出力をブロックバッファリングし、画面に何も出てこなくなる（2026-08-19b で修正）
    p = subprocess.Popen(cmd, shell=True, cwd=cwd, text=True, bufsize=1,
                         env=dict(os.environ, PYTHONUNBUFFERED='1'),
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    for line in p.stdout:
        if not quiet:
            print(line, end='')
    p.wait()
    return p.returncode



def _start_resource_watch(interval=60):
    """60秒ごとに RAM・ローカルディスク・ドライブの生死を1行で出す。

    ★目的は「落ちた瞬間に何が限界だったか」を出力に残すこと。
      切れたあともColabのセルに最後の1行が残るので、それだけで死因が分かる。
      読むだけ・出すだけで、動作には一切影響しない。
    """
    _t0 = time.time()

    def _loop():
        while True:
            try:
                mem = {}
                with open('/proc/meminfo') as f:
                    for ln in f:
                        k, _, v = ln.partition(':')
                        mem[k] = int(v.strip().split()[0])
                total = mem.get('MemTotal', 0) / 1048576
                avail = mem.get('MemAvailable', 0) / 1048576
                used = total - avail
                pct = (used / total * 100) if total else 0
                st = os.statvfs('/content')
                local_free = st.f_bavail * st.f_frsize / (1024 ** 3)
                try:
                    os.listdir('/content/drive/MyDrive')
                    drive = 'OK'
                except OSError as e:
                    drive = f'切断({e.errno})'
                warn = '  ⚠️メモリ逼迫' if pct >= 85 else ''
                # ★経過時間を出す。毎回だいたい同じ時間で切れるならColab側の時間切り、
                #   バラバラならブラウザ側の偶発的な切断と判別できる（2026-08-27a）
                el = int(time.time() - _t0)
                elapsed = f'{el // 3600}時間{el % 3600 // 60:02d}分' if el >= 3600 else f'{el // 60}分'
                line = (f'起動から{elapsed}  RAM {used:.1f}/{total:.1f}GB({pct:.0f}%)  '
                        f'ローカル空き {local_free:.1f}GB  ドライブ {drive}{warn}')
                print(f'[監視] {line}', flush=True)
                # ★ドライブにも残す。セッションが死ぬと画面の出力ごと消えてしまい、
                #   「何分で・どういう状態で落ちたか」が分からなくなるため（2026-08-27b）
                try:
                    jst = time.strftime('%m/%d %H:%M', time.gmtime(time.time() + 9 * 3600))
                    with open(SESSION_LOG, 'a', encoding='utf-8') as _lf:
                        _lf.write(f'{jst}  {line}\n')
                except Exception:
                    pass
            except Exception:
                pass
            time.sleep(interval)

    prev = globals().get('_res_watch')
    if prev is None or not prev.is_alive():
        t = threading.Thread(target=_loop, daemon=True)
        t.start()
        globals()['_res_watch'] = t
        print('✅ 監視を開始しました（60秒ごとに [監視] の行が出ます）')


WEBUI_DIR = '/content/drive/MyDrive/stable-diffusion-webui'
os.environ['GIT_TERMINAL_PROMPT'] = '0'   # gitが認証待ちで固まるのを防ぐ（git実行より前に置く）

# ===== GPU確認 =====
# ★★ここで runtime.unassign()＝ランタイム切断 を呼ぶ。条件を広げてはいけない。
#   2026-08-24b：「終了コードが0以外なら切る」に書き換えていたため、
#   nvidia-smi が一時的に失敗しただけ（NVMLエラー等・GPUは正常）でも切断してしまい、
#   「何もしていないのに勝手に切れる」状態になっていた。
#   元のコードと同じ「コマンドが存在しないときだけ」に戻した。
#   ★誤判定で切るのは、続行して失敗するより害が大きい。迷ったら切らない側に倒す。
_gpu = subprocess.run('nvidia-smi', shell=True, capture_output=True, text=True)
_gpu_out = (_gpu.stdout or '') + (_gpu.stderr or '')
if 'not found' in _gpu_out or 'No such file' in _gpu_out:
    print('GPUが設定されていないので、設定を確認してください')
    print('「ランタイム」→「ランタイムのタイプを変更」→ GPU を選んでください')
    runtime.unassign()
elif _gpu.returncode != 0:
    # 切らない。警告だけ出して続行する
    _first = _gpu_out.strip().splitlines()[0] if _gpu_out.strip() else '（出力なし）'
    print(f'⚠️ nvidia-smi が一時的に応答しませんでした（{_first}）')
    print('   GPU自体は使える可能性が高いので、このまま続行します')

# ===== ドライブのマウント =====
try:
    drive.mount('/content/drive')          # マウント済みなら何もしない
    os.listdir('/content/drive/MyDrive')   # ★本当に読めるか実際に確かめる
except Exception as e:
    raise SystemExit(
        f'\n【中断】Googleドライブにアクセスできません（{e}）\n'
        '  1. メニューの「ランタイム」→「ランタイムを接続解除して削除」\n'
        '     ※「再起動」では直りません。必ず「削除」を選んでください\n'
        '  2. つなぎ直して、このセルをもう一度実行してください\n'
    )

# ドライブの空き容量（不足していると書き込みに失敗してマウントごと落ちる）
try:
    _s = os.statvfs('/content/drive/MyDrive')
    _free_gb = _s.f_bavail * _s.f_frsize / (1024 ** 3)
    print(f'ドライブの空き容量：約 {_free_gb:.1f} GB')
    if _free_gb < 3:
        print('⚠️ 空き容量が少なすぎます。3GB以上空けてから実行してください')
except Exception:
    pass

# ===== 前回のセッションがどう終わったかを表示 =====
# ★落ちたときの記録が画面から消えても、ここに残る
SESSION_LOG = os.path.join(WEBUI_DIR, '_session_log.txt')
try:
    with open(SESSION_LOG, encoding='utf-8') as _lf:
        _prev = [l for l in _lf.read().splitlines() if l.strip()]
    if _prev:
        print('-' * 54)
        print('  前回のセッションの最後の記録（ここで落ちました）')
        for _l in _prev[-2:]:
            print(f'  {_l}')
        print('-' * 54)
except Exception:
    pass
try:
    _jst = time.strftime('%m/%d %H:%M', time.gmtime(time.time() + 9 * 3600))
    with open(SESSION_LOG, 'a', encoding='utf-8') as _lf:
        _lf.write(f'===== {_jst} 起動 (版 {SETUP_VERSION}) =====\n')
except Exception:
    pass

# ===== WebUI本体 =====
os.chdir('/content/drive/MyDrive')
if not os.path.exists('stable-diffusion-webui'):
    print('WebUI本体を取得しています…')
    sh('git clone -q https://github.com/bmxrebot0619-sys/stable-diffusion-webui')

# ============================================================
# ★2026-08-19 修正の中心
#   repositories フォルダをドライブから内蔵ディスクへ逃がす。
#   ・中身は起動時に自動で作り直されるので、ドライブに置く必要がない
#   ・ここが壊れると Bus error でドライブのマウントごと落ちる
#   ・内蔵ディスクなら毎回まっさらなので、壊れたまま残ることがない
#   （旧版にあった repositories/generative-models での「git stash」は削除。
#     後続の git pull が無く、何の役にも立たないまま壊れたファイルを踏むだけの行だった）
# ============================================================
def can_symlink_here(base):
    """このドライブでシンボリックリンクが作れるか、壊さずに試す。
    ★Googleドライブは対応していないことがある（OSError: [Errno 95] Operation not supported）。
      2026-08-24a：ここで落ちて起動できない報告があったため、
      「作れる前提」をやめて、作れないなら黙ってドライブ上のまま進める形にした。"""
    probe = os.path.join(base, '.symlink_probe')
    try:
        if os.path.islink(probe) or os.path.exists(probe):
            os.unlink(probe)
        os.symlink('/content', probe)
        os.unlink(probe)
        return True
    except OSError:
        try:
            if os.path.islink(probe):
                os.unlink(probe)
        except OSError:
            pass
        return False


REPOS_LOCAL = '/content/repositories'
REPOS_LINK = os.path.join(WEBUI_DIR, 'repositories')
SYMLINK_OK = can_symlink_here(WEBUI_DIR)

if SYMLINK_OK:
    # ★作れると確認できたときだけ、片付けてから切り替える。
    #   確認せずに消すと「消したのにリンクが張れない」最悪の状態になる
    os.makedirs(REPOS_LOCAL, exist_ok=True)
    if os.path.islink(REPOS_LINK):
        os.unlink(REPOS_LINK)
    elif os.path.isdir(REPOS_LINK):
        print('ドライブ上の repositories を片付けています（起動時に自動で作り直されます）…')
        shutil.rmtree(REPOS_LINK, ignore_errors=True)
        sh(f'rm -rf "{REPOS_LINK}"', quiet=True)
    try:
        os.symlink(REPOS_LOCAL, REPOS_LINK)
        print('✅ repositories を内蔵ディスクに切り替えました')
    except OSError as _e:
        os.makedirs(REPOS_LINK, exist_ok=True)
        print(f'ℹ️ repositories はドライブ上のまま使います（{_e.strerror}）')
else:
    # ドライブ上のまま。元のコードと同じ状態で、これで長く問題なく動いていた。
    # 本来の不具合（毎回走る git stash）は削除済みなので、ここは無くても直っている
    os.makedirs(REPOS_LINK, exist_ok=True)
    print('ℹ️ repositories はドライブ上のまま使います（このドライブはリンク非対応）')

# ===== 拡張機能の置き場所 =====
EXT_LINK = os.path.join(WEBUI_DIR, 'extensions')              # WebUIが見る場所
EXT_ONDRIVE = os.path.join(WEBUI_DIR, 'extensions_on_drive')  # 退避先（絶対に消さない）
EXT_LOCAL = '/content/extensions'
use_local_ext = str(_opt('拡張機能の置き場所', 'ドライブ（おすすめ）')).startswith('ローカル')
if use_local_ext and not SYMLINK_OK:
    # リンクが作れないドライブでは切り替えられない。退避だけして戻れなくなるのを防ぐ
    print('⚠️ このドライブはリンク非対応のため、拡張機能はドライブのまま使います')
    use_local_ext = False

if use_local_ext:
    os.makedirs(EXT_LOCAL, exist_ok=True)
    if os.path.isdir(EXT_LINK) and not os.path.islink(EXT_LINK):
        if os.path.exists(EXT_ONDRIVE):
            print('⚠️ 退避先がすでにあります。ドライブ側はそのまま残します')
        else:
            os.rename(EXT_LINK, EXT_ONDRIVE)
            print('ドライブの extensions を extensions_on_drive に退避しました（消していません）')
    if os.path.isdir(EXT_LINK) and not os.path.islink(EXT_LINK):
        print('⚠️ 切り替えできませんでした。ドライブのまま続行します')
    else:
        if os.path.islink(EXT_LINK):
            os.unlink(EXT_LINK)
        os.symlink(EXT_LOCAL, EXT_LINK)
        print('✅ 拡張機能を内蔵ディスクに切り替えました（毎回入れ直します）')
else:
    if os.path.islink(EXT_LINK):
        os.unlink(EXT_LINK)
    if not os.path.exists(EXT_LINK) and os.path.isdir(EXT_ONDRIVE):
        os.rename(EXT_ONDRIVE, EXT_LINK)
        print('退避していた拡張機能をドライブに戻しました')
    os.makedirs(EXT_LINK, exist_ok=True)

# ===== 拡張機能（無い物だけ入れる） =====
os.chdir(EXT_LINK)
exts = [
    "Bing-su/adetailer",
    "zixaphir/Stable-Diffusion-Webui-Civitai-Helper",
    "adieyal/sd-dynamic-prompts",
    "Mikubill/sd-webui-controlnet",
    "AI-Creators-Society/stable-diffusion-webui-localization-ja_JP",
    "AlUlkesh/stable-diffusion-webui-images-browser",
    "sugarkwork/mozaikukun",
    "picobyte/stable-diffusion-webui-wd14-tagger",
    "blue-pen5805/sdweb-easy-prompt-selector",
]
for ext in exts:
    ext_name = ext.split('/')[-1]
    if not os.path.exists(ext_name):
        print(f'拡張機能を入れています: {ext_name}')
        sh(f'git clone -q https://github.com/{ext}')

# sd-dynamic-promptsのファイルが壊れている場合は再クローン
if not os.path.exists('sd-dynamic-prompts/scripts/dynamic_prompting.py'):
    sh('rm -rf sd-dynamic-prompts', quiet=True)
    sh('git clone -q https://github.com/adieyal/sd-dynamic-prompts')

sh(f'rm -f "{EXT_LINK}/mozaikukun/install.py"', quiet=True)

# ===== Python 3.10 環境 =====
print('Python 3.10 を用意しています…')
sh('rm -f /etc/apt/sources.list.d/*ubuntugis* /etc/apt/sources.list.d/*graphics-drivers* '
   '/etc/apt/sources.list.d/*deadsnakes*', quiet=True)
sh('apt update -y -qq', quiet=True)
sh('apt install python3.10-venv python3.10-dev -y --fix-missing', quiet=True)

# ★2026-09-10b追加：Colabがベースイメージの既定を Python 3.12 に切り替えた影響で、
#   標準リポジトリに python3.10 自体が無いケースが出てきた
#   （E: Unable to locate package python3.10-venv / python3.10-dev）。
#   複数Pythonバージョン配布の定番である deadsnakes PPA から取り直す。
#   WebUI本体がPython3.10前提のため、3.12へ乗り換える方向にはしない。
if not shutil.which('python3.10'):
    print('  標準リポジトリに python3.10 が見つからないため、deadsnakes PPA から取得します…')
    sh('apt install -y software-properties-common', quiet=True)
    sh('add-apt-repository -y ppa:deadsnakes/ppa', quiet=True)
    sh('apt update -y -qq', quiet=True)
    sh('apt install python3.10 python3.10-venv python3.10-dev -y --fix-missing', quiet=True)

sh('curl -sS https://bootstrap.pypa.io/get-pip.py | python3.10', quiet=True)

# ★2026-09-10a追加：ここが失敗しても quiet=True で握りつぶされ、
#   ずっと後段の「/content/venv/bin/python: not found」としてしか症状に出ず、
#   本当の原因（apt installの失敗内容）が見えなかった。
#   ここで python3.10 自体の有無を実際に確かめ、無ければ本当のエラーを出して止める。
if not shutil.which('python3.10'):
    print('\n' + '=' * 54)
    print('  ⚠️ python3.10 の用意に失敗しました（deadsnakes PPA追加後も解決せず）')
    print('=' * 54)
    _diag = subprocess.run('apt-get install python3.10 python3.10-venv python3.10-dev -y --fix-missing',
                           shell=True, capture_output=True, text=True)
    print((( _diag.stdout or '') + (_diag.stderr or '')).strip()[-3000:] or '（エラー出力なし）')
    raise SystemExit(
        '\n【中断】python3.10 の用意に失敗しました。\n'
        '  上に出ている赤い文字（エラー内容）の最後の数行を田口さんに送ってください。\n'
    )

# ===== 自動切断タイマー =====
_cut_map = {"無制限": -1, "1時間": 3600, "2時間": 7200, "3時間": 10800,
            "4時間": 14400, "6時間": 21600, "8時間": 28800}
_cut_label = str(_opt('自動切断', '無制限'))
cut_time = _cut_map.get(_cut_label, -1)

# セルを何度実行してもタイマーが増えないよう、前のタイマーを止めてから張り直す
_prev = globals().get('_auto_cut_timer')
if _prev is not None:
    try:
        _prev.cancel()
    except Exception:
        pass
_auto_cut_timer = None
if cut_time != -1:
    _auto_cut_timer = threading.Timer(cut_time, runtime.unassign)
    _auto_cut_timer.daemon = True
    _auto_cut_timer.start()
    print(f'自動切断：{_cut_label}後にランタイムを切断します')

# ===== タブ操作の自動維持（任意・既定OFF） =====
# ★背景（2026-09-17）：生成は別タブ（gradio.liveのリンク）で行うため、
#   このColabノートブックのタブ自体は誰にも触られないまま放置される。
#   GPUは正常に動いていても、Colab側は「操作されていないタブ」とみなして
#   セッションを切ることがある（RAM・ディスクは正常なまま突然切れる、という報告と一致）。
#   ここでは無害なマウス移動イベントを定期的に流すだけで、実際のボタン操作は一切しない。
# ★既定は False。既存・今後のノートブックを問わず、明示的にONにした人だけに効かせる
#   （公開リポジトリ＝全員のGoogleアカウントで動くため、無断で有効化しない）。
if bool(_opt('タブ操作を自動維持', False)):
    try:
        from IPython.display import Javascript, display
        display(Javascript('''
        (function(){
          if (window.__sdKeepAlive) clearInterval(window.__sdKeepAlive);
          window.__sdKeepAlive = setInterval(function(){
            document.dispatchEvent(new MouseEvent('mousemove', {
              bubbles: true,
              clientX: Math.floor(Math.random() * window.innerWidth),
              clientY: Math.floor(Math.random() * window.innerHeight),
            }));
          }, 60000);
        })();
        '''))
        print('✅ タブ操作の自動維持を開始しました（Colabがアイドルと誤認しにくくなります）')
    except Exception as _e:
        print(f'⚠️ タブ操作の自動維持を開始できませんでした（続行します）: {_e}')

os.environ["STABLE_DIFFUSION_REPO"] = "https://github.com/Kantyadoram/stable-diffusion-stability-ai.git"
os.environ["STABLE_DIFFUSION_COMMIT_HASH"] = "7435a5be1050962a936a4ef624b43814ee8824a8"

print("セットアップ完了")

# ===== 実行環境（venv）を作る =====
if not os.path.exists(WEBUI_DIR):
    raise SystemExit('エラー: stable-diffusion-webuiフォルダが見つかりません')

os.chdir(WEBUI_DIR)
if os.path.exists('/content/venv'):
    shutil.rmtree('/content/venv')

print("環境を構築中...（3〜5分かかります。画面が止まって見えても待ってください）")
sh('python3.10 -m venv /content/venv', quiet=True)
VENV_PYTHON = "/content/venv/bin/python"
VENV_PIP = "/content/venv/bin/pip"

# ★2026-09-10追加：venv作成の失敗も検知せず、後続がいきなり
#   「/content/venv/bin/python: not found」で落ちて原因が分からなかった。
#   ここで実際にできているか確かめ、無ければ本当のエラーを出して止める。
if not os.path.exists(VENV_PYTHON):
    print('\n' + '=' * 54)
    print('  ⚠️ Python実行環境(venv)の作成に失敗しました')
    print('=' * 54)
    _diag = subprocess.run('python3.10 -m venv /content/venv', shell=True, capture_output=True, text=True)
    print(((_diag.stdout or '') + (_diag.stderr or '')).strip() or '（エラー出力なし）')
    raise SystemExit(
        '\n【中断】venv の作成に失敗しました。\n'
        '  上に出ている赤い文字（エラー内容）の最後の数行を田口さんに送ってください。\n'
    )

for _cmd in [
    f'{VENV_PYTHON} -m pip install -q "pip==23.3.1" setuptools wheel',
    f'{VENV_PIP} install -q -r requirements_versions.txt',
    f'{VENV_PIP} install -q git+https://github.com/openai/CLIP.git --no-build-isolation',
    f'{VENV_PIP} install -q "fastapi==0.94.0" "pydantic<2.0.0" "typing-extensions>=4.5.0" '
    f'"protobuf==3.20.3" pytorch-lightning==1.9.4 '
    f'"dynamicprompts[attentiongrabber,magicprompt]~=0.31.0" "send2trash~=1.8"',
    f'{VENV_PIP} install -q rich ultralytics controlnet_aux',
    f'{VENV_PIP} install -q "Pillow==10.4.0" "numpy==1.26.4" "urllib3<2.0.0"',
    f'{VENV_PIP} install -q "opencv-python-headless==4.10.0.84" --force-reinstall --no-deps',
]:
    sh(_cmd + ' 2>/dev/null', quiet=True)

# ===== 常用設定をUIの初期値に焼き込む =====
# 値はノートブック側のプルダウン・入力欄から受け取る（この本体には書かない）
_uicfg_path = os.path.join(WEBUI_DIR, 'ui-config.json')
try:
    with open(_uicfg_path, encoding="utf-8") as _f:
        _ui = json.load(_f)
    _updates = {
        "txt2img/Prompt/value": _opt('FIXED_PROMPT_PREFIX', ''),
        "txt2img/Negative prompt/value": _opt('FIXED_NEGATIVE', ''),
        "txt2img/Width/value": _opt('DEF_WIDTH', 832),
        "txt2img/Height/value": _opt('DEF_HEIGHT', 1216),
        "txt2img/CFG Scale/value": _opt('DEF_CFG', 3),
        "customscript/sampler.py/txt2img/Sampling steps/value": _opt('DEF_STEPS', 30),
        "customscript/sampler.py/txt2img/Sampling method/value": _opt('DEF_SAMPLER', 'DPM++ 2M'),
        "txt2img/Hires. fix/value": _opt('DEF_HIRES', True),
        "txt2img/Upscaler/value": _opt('DEF_UPSCALER', 'Latent'),
        "txt2img/Upscale by/value": _opt('DEF_UPSCALE_BY', 1.5),
        "txt2img/Hires steps/value": _opt('DEF_HIRES_STEPS', 10),
        "txt2img/Denoising strength/value": _opt('DEF_DENOISE', 0.5),
    }
    for _k, _v in _updates.items():
        if _k in _ui:  # 既存のキーだけ更新（存在しないキーは触らない＝安全）
            _ui[_k] = _v
    with open(_uicfg_path, "w", encoding="utf-8") as _f:
        json.dump(_ui, _f, ensure_ascii=False, indent=4)
    print("✅ UIの初期値を常用設定に更新しました（次の起動からこの値で始まります）")
except Exception as _e:
    print(f"⚠️ UI初期値の更新をスキップ（ui-config.jsonが未生成かも）: {_e}")

_start_resource_watch()
print("起動中...（1〜2分ほどで、下に https://〜.gradio.live のリンクが出ます）")
print("★もし生成の途中で切れたら、いちばん下の [監視] の行をそのまま送ってください。")
print("※このセルは動かしたままにしてください。止めるとリンクも切れます。\n")

# ★「-u」と PYTHONUNBUFFERED の両方が必要。
#   どちらか欠けると出力が溜め込まれ、gradioのアドレスが画面に出てこない
#   （2026-08-19b：アドレスが表示されないという報告を受けて修正）
_launch_cmd = (f'{VENV_PYTHON} -u launch.py --share --enable-insecure-extension-access '
               f'--disable-safe-unpickle --no-half-vae --skip-install')
_p = subprocess.Popen(_launch_cmd, shell=True, cwd=WEBUI_DIR, text=True, bufsize=1,
                      env=dict(os.environ, PYTHONUNBUFFERED='1', MPLBACKEND='Agg'),
                      stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
# ★出力を垂れ流さない（2026-08-24d）
#   生成のたびに出る進捗バー（12%|█▌ …）を全部ノートブックに書き込むと、
#   保存されるファイルが巨大になり、次に開いたとき真っ黒のまま開けなくなる。
#   ブラウザのメモリも食い潰すため、生成中に切れる原因にもなりうる。
_PROGRESS_RE = re.compile(r'\d+%\|')
_IMPORTANT_RE = re.compile(r'(Error|error|ERROR|Traceback|Exception|Errno|gradio\.live|\[監視\])')
_MAX_LINES = 3000
_shown = False
_printed = 0
_skipped = 0
for _raw in _p.stdout:
    # 進捗バーは \r で上書きされる。最後の状態だけ見ればよい
    _line = _raw.split('\r')[-1] if '\r' in _raw else _raw
    if _PROGRESS_RE.search(_line):
        _skipped += 1
        continue
    if _printed >= _MAX_LINES and not _IMPORTANT_RE.search(_line):
        _skipped += 1
        if _skipped % 2000 == 0:
            print(f'…（出力が多いため省略中：{_skipped}行。エラーと監視は必ず表示します）', flush=True)
        continue
    print(_line, end='' if _line.endswith('\n') else '\n')
    _printed += 1
    if 'gradio.live' in _line and not _shown:
        _url = [w for w in _line.split() if 'gradio.live' in w]
        if _url:
            _shown = True
            print('\n' + '=' * 54)
            print('  ★ Stable Diffusion はこちらから開いてください')
            print(f'  {_url[0].rstrip(chr(34) + chr(39) + ",")}')
            print('=' * 54 + '\n')
_p.wait()

# ★リンクが出ないまま終わった＝失敗。黙って終わらせず、何が起きたかを必ず出す
#   （2026-08-19c：エラーが出ているのに「アドレスが出ない」としか分からず、
#     原因の切り分けに何往復もしたため追加）
if not _shown:
    print('\n' + '=' * 54)
    print('  ⚠️ アドレスが出ないまま終了しました')
    print('=' * 54)
    print('  上に出ている赤い文字（Traceback）の【最後の1行】を')
    print('  田口さんに送ってください。それだけで原因が分かります。')
    print('  ※長い部分は全部ノイズなので、送らなくて大丈夫です。')
    print('=' * 54)
