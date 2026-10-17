# GitHubへのアップロード準備

## アップロードするフォルダー

稼働中の作業フォルダーには本・PDF・API設定・個人用検証記録が含まれます。準備済みの`epub-proofreader-github`フォルダーを使ってください。公開用には次を除いています。

- `.data`、`data`、`.venv`、`.tools`、`node_modules`、ビルド済み`dist`。
- APIキー・暗号化キー・`.env`・SQLite・作業データ・個人用AI接続先。
- 実書籍を使った画面画像・個人環境の検証記録。

独自制作の` samples/ `と自動テストは含みます。PDF表示資材はビルド時に準備されます。初期AI設定はlocalhostのOllamaの例で、個人の接続先はありません。

## 初回アップロード

公開先は `fhama74/epub_proofreader`（Public）です。GitHubで空のリポジトリを作成し、READMEや.gitignoreを自動追加せず、表示されたリポジトリURLを使います。ローカルのGitリポジトリは準備済みで、まだコミット・送信していません。

```sh
# 公開用フォルダー内で実行
git status --short
git add .
git diff --cached --stat
# 送信対象の確認後
git commit -m "Initial EPUB Proofreader"
git remote add origin YOUR_REPOSITORY_URL
git push -u origin main
```

`YOUR_REPOSITORY_URL`は自分のリポジトリURLに置き換えます。GitHubへのログインやSSH設定は別途必要です。自分用の設定、保存データ、鍵を追加しないでください。`.gitignore`は誤登録を防ぐ補助で、既に追跡したファイルは自動的には除外しません。

## アップロード後の確認

Actionsで通常テストとDocker検証が成功することを確認します。Docker検証はイメージのビルド、起動、サンプルEPUBの保存と実EPUBCheck、コンテナ再作成後のデータ保持を調べます。イメージをレジストリへ自動公開する処理はありません。

## ライセンス

自作コードのライセンスはMITです。`LICENSE`と`THIRD_PARTY_NOTICES.md`を参照してください。依存ライブラリーやEPUBCheckにはそれぞれのライセンスがあります。自分の本やPDFは公開用ソースへ含めません。
