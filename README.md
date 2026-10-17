# EPUB Proofreader

## 概要

**EPUB Proofreader** は、日本語のOCRから作成したEPUBを、元のPDFと見比べながら校正するためのWebアプリです。縦書きとルビに対応し、AIが見つけた誤認識の候補を確認しながら修正できます。

## 主な機能

- **EPUBの表示・編集**：縦書き・横書きの本文を表示し、段落や文を選んで校正。文字の修正に加え、段落の挿入・分割・結合にも対応します。
- **原本PDFとの照合**：PDFを横に表示し、文字レイヤーがある場合は校正箇所に合わせてページを自動追従します。手動で対応ページを指定することもできます。
- **ルビの校正**：親文字と読みを専用画面で編集し、必要に応じて親文字の範囲を調整できます。
- **AIによる誤認識の検出**：OpenAI、Google Gemini、Anthropic Claude、Ollamaに対応。現在の段落・章・書籍全体を検査し、指摘箇所へ移動して確認できます。
- **校正の進捗管理**：AIの指摘を確認・修正・保留でき、編集履歴、Undo／Redo、検索・置換も利用できます。
- **プロジェクト保存とEPUB発行**：作業は自動保存。原本を保持したまま作業を進め、校正後のEPUBを版として発行できます。作業データの書き出し・復元にも対応します。
- **iPadでの利用**：タッチ操作向けの読書表示と校正画面を用意しています。

## 特徴

- **原本を守る設計**：AIの提案は自動反映せず、利用者が確定した修正だけを本文に適用します。元のEPUBは保持します。
- **日本語の書籍向け**：縦書き、ルビ、旧字や歴史的仮名遣いなどを考慮し、OCR由来の誤りを見つけやすくします。
- **EPUB構造を維持**：元のXHTMLを編集し、プレビュー画面からEPUBを作り直しません。発行時には構造を検証します。
- **ローカルで作業を管理**：プロジェクトや校正結果をローカルに保存。Ollamaを使えばローカルAIによる検査も可能です。クラウドAIを利用する場合は、検査対象のテキストが各サービスへ送信されます（PDF画像は送信しません）。

## セットアップ

### Docker（推奨）

Docker Composeが使える環境なら、ソースやPythonの取得なしで起動できます。

```bash
mkdir epub-proofreader
cd epub-proofreader
curl -fL https://raw.githubusercontent.com/fhama74/epub_proofreader/main/compose.ghcr.yaml -o compose.yaml
docker compose pull
docker compose up -d
```

初回に保存先と暗号化キーを自動作成します。起動後は **http://127.0.0.1:8000/** を開いてください。詳しい設定・バックアップ・移行・ソースからのビルドは [Docker運用手順](docs/DOCKER.md) を参照してください。

### Pythonで起動

Python 3.12以上、[uv](https://docs.astral.sh/uv/)、Node.js／pnpmが必要です。GitHubのリポジトリを取得したディレクトリで実行します。

```bash
cd frontend
pnpm install --frozen-lockfile
pnpm build
cd ..

uv sync --locked
uv run uvicorn epub_proofreader.app:app --app-dir backend --host 127.0.0.1 --port 8000 --workers 1 --timeout-graceful-shutdown 5
```

起動後、ブラウザで **http://127.0.0.1:8000/** を開いてください。

クラウドAIのAPIキーを保存する場合は、暗号化キーの設定が必要です。ローカル環境では次のスクリプトを利用できます。

```bash
python3 scripts/configure_local.py
```

AIエンジンの接続先とモデルは、アプリ内の「AI検査・結果一覧」→「エンジン管理」で設定できます。

## ドキュメント

[Docker・運用手順](docs/DOCKER.md)

## ライセンス

自作コードは [MIT License](LICENSE) です。依存ライブラリ等のライセンスは [第三者ライセンス](THIRD_PARTY_NOTICES.md) を参照してください。
