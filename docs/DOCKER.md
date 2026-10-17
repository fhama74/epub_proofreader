# Debian / Docker運用

Docker EngineとDocker Compose v2を導入したDebianで動かす構成です。公開イメージを使う場合、ホストへのPython・Node.js・Gitの導入は不要です。ソースからビルドする手順の初期設定スクリプトでは、ホストのPython 3を使います。

## 公開イメージで新しく始める（Git・Python不要）

Docker Compose v2を利用します。Intel/AMDのLinuxとARM64（Apple Siliconを含む）に対応します。

```sh
mkdir epub-proofreader
cd epub-proofreader
curl -fL https://raw.githubusercontent.com/fhama74/epub_proofreader/main/compose.ghcr.yaml -o compose.yaml
docker compose pull
docker compose up -d
```

`http://127.0.0.1:8000/` を開きます。初期化用のコンテナが `data/` と `secrets/ai_secret_key` を準備して終了し、その後アプリが起動します。初期化用コンテナの終了コード0は正常です。既存のキーは置き換えません。既存データがあるのにキーがない場合は移行ミスを防ぐため停止します。

ポート・公開先・イメージを変更する場合は、同じフォルダーに `.env` を作成します（任意）。

```dotenv
EPROOF_BIND_ADDRESS=127.0.0.1
EPROOF_PORT=8000
EPROOF_IMAGE=ghcr.io/fhama74/epub_proofreader:latest
```

更新は `docker compose pull`、`docker compose up -d` の順で実施します。更新前に下記の保存領域とキーをバックアップしてください。再現可能な版を固定する場合は、GHCRの `sha-<40桁のコミットID>` タグまたはダイジェストを `EPROOF_IMAGE` に指定します。

この公開イメージは、GitHubログインなしで取得できます。

## ソースからビルドする場合

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

## ブラウザーごとの位置保存

最後に開いたプロジェクト、章・段落・文、本文の表示位置、PDFのページ・倍率・表示位置を、各ブラウザーのローカル保存領域に記憶します。同じブラウザープロファイル・同じ接続先URLで開くと復元します。別のブラウザーでの位置移動では上書きしません。通常の位置移動はサーバーへ保存せず、作業データの書き出し時にはそのブラウザーの表示位置も含めます。

ブラウザーのサイトデータを消した場合やプライベートモード終了時には、この記憶が失われることがあります。IPアドレス経由とドメイン経由など、接続先が異なる場合も別の保存領域です。共有本文が編集されていた場合は段落・文を再照合し、古いスクロール量は使わず、その校正箇所に移動します。

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

ヘルスチェック、画面・PDF資材の配信、プロジェクト保存・再作成後の復元、実EPUBCheckを検証します。GitHub Actionsにも同じ手順を設定しています。ソースからのDocker起動・EPUBCheck・再作成後のデータ保持はGitHub ActionsのLinux環境で検証済みです。GHCR公開時にもAMD64・ARM64の両方で検証し、公開済みイメージの取得・起動まで成功しています。Debian実機とDocker Desktop実機での操作確認は別途必要です。

参考：[Docker Composeのsecrets](https://docs.docker.com/compose/how-tos/use-secrets/)、[Composeの起動と設定確認](https://docs.docker.com/compose/gettingstarted/)。

## イメージの公開・ライセンス

GitHub Actionsの `Publish GHCR image` を手動実行するか、`v` で始まるタグをpushすると公開します。両CPUで起動・EPUBCheck・保存データとキーの保持を検証後、`latest` と `sha-<コミットID>` を公開します。タグからの実行では `v` を除いた版タグも追加します。通常のmainへのpushではイメージを更新しません。

GitHub Actionsの一時的な `GITHUB_TOKEN` を使い、利用者のAPIキーや個人のGitHubトークンをイメージに入れません。別のリポジトリへ複製して公開する場合、初回のパッケージがPrivateになることがあります。その場合はPackages設定でPublicに変更してから、ログインなしの取得を確認してください。

対応するGPL/LGPLのDebianソースとSaxonのソースは、同じコミットの `container-<コミットID>` リリースへ別添します。大きなソースアーカイブは通常のイメージ取得には含まれません。詳しくは [コンテナのソースとライセンス](CONTAINER_SOURCES.md) を参照してください。
