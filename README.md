# sd-colab-setup

Stable Diffusion WebUI を Google Colab で起動するためのセットアップ本体です。

Colab のノートブックからこのファイルを読み込んで実行します。
**ここを更新すると、次回の起動から全員に反映されます**（ノートブックの貼り替えは不要）。

## 使い方

Colab の1セル目の末尾に、次を書きます。

```python
import os
_URL = 'https://raw.githubusercontent.com/akiterupapa-cpu/sd-colab-setup/main/setup.py'
os.system(f'curl -sfL "{_URL}" -o /content/sd_setup.py')
exec(open('/content/sd_setup.py', encoding='utf-8').read())
```

プロンプトの初期値・画像サイズなどの設定は、この行より**前**にノートブック側で定義します。
`setup.py` はそれを読み取って使い、未定義なら既定値で動きます
（古いノートブックから呼ばれても落ちないようにするため）。

## 設計上のきまり

- **`setup.py` には IPython のマジック（`!コマンド` や `%cd`）を書かない。**
  普通の Python として構文チェックできる状態を保つ（`python3 -m py_compile setup.py`）。
  シェル実行は `sh()`、ディレクトリ移動は `os.chdir()` を使う。
- **ノートブック側の設定は必ず `_opt('名前', 既定値)` で読む。**
  直接参照すると、設定が未定義な古いノートブックから呼ばれたときに落ちる。
- **`SETUP_VERSION` を必ず更新する。** 起動時に画面へ出るので、
  「古い版が動いているのか」をログだけで判別できる。
- **個人の設定値（プロンプト等）はここに置かない。** ノートブック側に置く。

## 修正履歴

### 2026-08-19a

Drive のマウントが起動途中で落ちる事故（`Bus error` → `OSError: [Errno 107]
Transport endpoint is not connected`）への対応。

| # | 内容 | 理由 |
|---|---|---|
| 1 | `repositories/generative-models` での `git stash` を削除 | 後続に `git pull` が無く何もしていなかった。2回目以降に無条件で走る唯一の Drive 上 git 操作で、破損ファイルを読んで `Bus error` を起こし Drive のマウントごと落としていた |
| 2 | `repositories` を Drive から `/content` へ逃がす（シンボリックリンク） | 中身は起動時に自動生成されるため Drive に置く必要がない。ローカルなら毎回まっさらで、壊れたまま残らない |
| 3 | マウントの生死を `os.listdir` で実測し、死んでいたら手順を出して中断 | 先へ進むと無関係なトレースバックが200行以上出て原因が埋もれる |
| 4 | Drive の空き容量を起動時に表示（3GB未満で警告） | 容量不足も書き込み失敗＝マウント死の原因になる |
| 5 | 拡張機能もローカルへ逃がす選択肢を追加（最後の手段） | Drive 側は削除せず `extensions_on_drive` へ退避。元に戻せる |
| 6 | `GIT_TERMINAL_PROMPT` の設定を git 実行より前へ移動 | 旧版は clone の後に設定していて効いていなかった |
| 7 | 存在しない環境変数 `GIT_COMMAND_TIMEOUT` を削除 | git はこの変数を読まない。効いているつもりの60秒制限は掛かっていなかった |
| 8 | 未使用の `import tensorflow` を削除 | 一度も使われないのに読み込みで時間とメモリを消費する |
| 9 | 自動切断を `threading.Timer` に変更し、張り直す前に前のをキャンセル | 旧版は `Thread`+`sleep` で止められず、セル実行のたびにタイマーが増えていた |

## 未対応

WebUI 本体の取得元 `github.com/bmxrebot0619-sys/stable-diffusion-webui` が
コミット指定なし（常に最新を取得）。動作確認済みのコミットで固定するのが望ましい。
内部リポジトリ側（`Kantyadoram/stable-diffusion-stability-ai`）は固定済み。
