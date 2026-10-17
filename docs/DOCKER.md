# Debian / Docker運用

Docker EngineとDocker Compose v2を導入したDebianで動かす構成です。PythonとNode.jsはイメージ内に入るためホストへの導入は不要です。初期設定スクリプトにはホストのPython 3を使います。

## 新しく始める

公開用ソースのフォルダーで実行します。

```sh
python3 scripts/init_docker.py
# 設定確認。必要なら .env のポートやAI接続先を編集
# Mac版が8000で動作中なら EPROOF_PORT=8002 など別の値にする
docker compose config --quiet
docker compose up --build -d
docker compose ps
```

`http://127.0.0.1:8000/` を開きます。`.env`で変更した場合はそのポートを使います。ビルド時はnpm/PyPI/Debianと公式EPUBCheck配布へのインターネット接続が必要です。PDF描画資材とJava・EPUBCheckはイメージ内に入り、実行時のCDN取得はありません。AIは画面から手動で開始した場合だけ呼び出します。

初期化は`data/`、`secrets/ai_secret_key`、`.env`を作り、既存の鍵と設定を上書きしません。保存済みデータがあるのに鍵がない場合は停止します。APIキーそのものは画面で登録します。

## 保存・停止・更新

- `./data/library.sqlite3`：本・PDF・編集・発行版・AI情報。
- `./secrets/ai_secret_key`：APIキー保存用の暗号化キー。データとは別に保存。
- `.env`：接続・ポート設定。APIキーは記入しません。

```sh
docker compose logs --tail 100 -f
docker compose stop
# 再開
docker compose up -d
# ソース更新後
docker compose up --build -d
```

コンテナの停止・再作成で`./data`は消えません。バックアップはAIを画面で一時停止し、コンテナ停止後に`data/`全体をコピーします。鍵は別の保管先へコピーしてください。復元には保存時と同じ鍵が必要です。再起動後のAIジョブは画面から手動で再開します。

## 今のMac環境から移す

1. 現在の画面でAIジョブを一時停止し、サーバーを停止します。
2. 現在のデータフォルダー（通常`.data/`）全体を、Docker用フォルダーの`data/`へコピーします。元データは残します。
3. 現在の`AI_SECRET_KEY_FILE`のファイルを`secrets/ai_secret_key`へコピーします。`AI_SECRET_KEY`を環境変数で設定していた場合は、その同じ値をファイルに保存します。鍵を新しく生成してはいけません。
4. `.env.example`を`.env`へコピーし、接続先を設定して起動します。
5. 保存済みプロジェクトとPDF、編集・発行版、登録済みAIエンジンの接続を確認してから元環境を片付けます。

AIを使っていなかった環境で鍵が存在しない場合は、新しい鍵を作れますが、既存の暗号化済みAPIキーがないことを先に確認してください。移行を誤って進めないため、初期化スクリプトは既存データがある環境での自動生成を拒否します。

## Ollamaの接続

コンテナの`localhost`はコンテナ自身です。Dockerホスト上のOllamaは、エンジン画面の接続先を`http://host.docker.internal:11434`へ変更します。`.env`の`AI_ALLOWED_ORIGINS`に同じ起点URLを指定します。ComposeはDebianにも`host-gateway`を追加します。Ollama側もコンテナから到達できるアドレスで待ち受ける必要があります。

別サーバーのOllamaを使う場合は、そのURLを許可リストと画面の両方に設定します。クラウド3社は公式URLだけを使います。

## iPadから開く

既定はホストの127.0.0.1限定です。iPadで使う場合は`.env`の`EPROOF_BIND_ADDRESS`をホストのLANまたはTailscaleのIPに変更し、`docker compose up -d`で反映します。iPadからそのIPとポートを開きます。

ログイン・ユーザーごとのアクセス制御は未実装です。同じサーバーへ接続した人は同じ保存領域を使います。信頼できるLAN/VPNの範囲で使い、インターネットへ直接公開しない構成です。

## 起動確認

新規の検証環境専用です。独自サンプルのプロジェクトを作成し、AIは呼び出しません。

```sh
python3 scripts/docker_smoke.py --state /tmp/eproof-smoke.json --create
docker compose down
docker compose up -d
python3 scripts/docker_smoke.py --state /tmp/eproof-smoke.json
```

ヘルスチェック、画面・PDF資材の配信、プロジェクト保存・再作成後の復元、実EPUBCheckを検証します。GitHub Actionsにも同じ手順を設定しています。開発MacではDocker daemonとComposeが未導入のため、コンテナビルド・Debian実機での起動は未検証です。GitHub Actionsの成功を確認してから運用へ移します。

参考：[Docker Composeのsecrets](https://docs.docker.com/compose/how-tos/use-secrets/)、[Composeの起動と設定確認](https://docs.docker.com/compose/gettingstarted/)。
