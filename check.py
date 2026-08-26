#!/usr/bin/env python3
"""setup.py の検品。push する前に必ず走らせる（機械で止める）。

★2026-08-19c：整理のつもりで os.environ['MPLBACKEND'] を消してしまい、
  launch.py が起動前に落ちた。「気をつける」ではなく、消したら落ちる形で止める。
"""
import ast, pathlib, py_compile, sys

SRC = pathlib.Path(__file__).with_name('setup.py')
fail = []

# 1) 普通のPythonとして読めること（IPythonのマジックを書いていないことの担保）
try:
    py_compile.compile(str(SRC), doraise=True)
    print('✅ 構文チェック')
except py_compile.PyCompileError as e:
    fail.append(f'構文エラー: {e}')

src = SRC.read_text(encoding='utf-8')

# 2) 消してはいけない環境変数（消えると起動前に落ちる／静かに壊れる）
REQUIRED_ENV = {
    'MPLBACKEND': 'Colabの既定値が venv 側に漏れて matplotlib が ValueError で落ちる',
    'GIT_TERMINAL_PROMPT': 'gitが認証待ちで固まる',
    'STABLE_DIFFUSION_REPO': '本体の取得先が変わる',
    'STABLE_DIFFUSION_COMMIT_HASH': 'バージョン固定が外れる',
    'PYTHONUNBUFFERED': '出力が溜め込まれてgradioのアドレスが画面に出ない',
}
for name, why in REQUIRED_ENV.items():
    if name not in src:
        fail.append(f'{name} が無い → {why}')
    else:
        print(f'✅ {name}')

# 3) 起動は必ず -u 付き（無いと出力が出ない）
if '-u launch.py' not in src:
    fail.append('launch.py を -u 付きで起動していない → gradioのアドレスが画面に出ない')
else:
    print('✅ -u 付き起動')

# 4) 版が更新されているか人が判断できるよう表示
for line in src.splitlines():
    if line.startswith('SETUP_VERSION'):
        print(f'ℹ️  {line}（★直したら必ず上げる）')

# 5) 公開リポジトリなので個人の設定値が混ざっていないこと
NG = ['watercolor', 'tatami', '1girl', 'gradio.live/']
for w in NG:
    if w in src and w != 'gradio.live/':
        fail.append(f'個人設定らしき文字列が含まれている: {w}')
print('✅ 個人設定の混入なし' if not any(w in src for w in NG[:3]) else '')

# 6) ランタイム切断の条件を広げていないこと（誤判定で切ると「勝手に切れる」になる）
if "runtime.unassign()" in src:
    if "'not found' in _gpu_out" not in src:
        fail.append("GPU判定が『コマンドが無いとき』以外でも切断しうる "
                    "→ nvidia-smi の一時的な失敗でランタイムが落ちる")
    else:
        print('✅ 切断条件（コマンド不在時のみ）')

print('-' * 46)
if fail:
    print('❌ 検品NG')
    for f in fail:
        print(f'   - {f}')
    sys.exit(1)
print('✅ 検品すべて合格')
