# 🏥 LINE ヘルス管理 Bot

LINEで食事内容を送ると、Gemini AIがカロリー計算・栄養分析を行い内容をプレビュー表示します。**確認後**にGoogleスプレッドシートに記録される完全自動のヘルス管理システムです。

## アーキテクチャ

```
LINE ユーザー
    │ テキスト送信（例：「昼：牛丼並盛」）
    ▼
LINE Messaging API（Webhook）
    │
    ▼
Python バックエンド（FastAPI on Render）
    └─→ Gemini API（カロリー・PFC・アドバイス生成）
    │
    ▼
LINEに「確認プレビュー」を返信 + Quick Reply（「記録する」「キャンセル」）
    │
    │「記録する」タップ
    ▼
GAS Web API → Google スプレッドシートに appendRow
    │
    ▼
LINEに「記録完了」を返信
```

## ファイル構成

```
HealthManager/
├── main.py           # FastAPI バックエンド
├── requirements.txt  # Python 依存ライブラリ
├── .env.example      # 環境変数テンプレート
├── Code.gs           # Google Apps Script
└── .gitignore
```

---

## セットアップ手順

### Step 1: Gemini API キーの取得

1. [Google AI Studio](https://aistudio.google.com/app/apikey) にアクセス
2. 「APIキーを作成」をクリック
3. 生成されたキーをコピーして控える（後で `GEMINI_API_KEY` に設定）

---

### Step 2: Google スプレッドシートの準備

1. [Google スプレッドシート](https://sheets.google.com) で新規スプレッドシートを作成
2. URLの `https://docs.google.com/spreadsheets/d/` と `/edit` の間にある文字列が **スプレッドシートID**
   ```
   例: https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms/edit
   　　 ID: 1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms
   ```

---

### Step 3: Google Apps Script (GAS) のデプロイ

1. [Google Apps Script](https://script.google.com/) を開き、「新しいプロジェクト」を作成
2. エディタ内のコードを全て削除し、`Code.gs` の内容を貼り付ける
3. 1行目の `SPREADSHEET_ID` を先ほどのIDに変更する
   ```javascript
   const SPREADSHEET_ID = "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms"; // ← 変更
   ```
4. 上部メニュー「デプロイ」→「新しいデプロイ」をクリック
5. 設定:
   - **種類**: ウェブアプリ
   - **説明**: LINE Health Bot（任意）
   - **次のユーザーとして実行**: 自分
   - **アクセスできるユーザー**: 全員（匿名ユーザーを含む）
6. 「デプロイ」→ Google アカウントで承認 → URLをコピー
   ```
   例: https://script.google.com/macros/s/AKfycbxXXXXXXXX/exec
   ```
   このURLが `GAS_ENDPOINT_URL` になります。

> **注意**: コードを変更するたびに「新しいデプロイ」が必要です（「デプロイを管理」→「編集」でも可）。

---

### Step 4: LINE Developers の設定

1. [LINE Developers Console](https://developers.line.biz/console/) にアクセス
2. 「プロバイダー作成」→「チャネル作成」→「Messaging API」を選択
3. 必要事項を入力してチャネルを作成
4. **Channel Secret** を取得:
   - 「チャネル基本設定」タブ → 「Channel secret」→「発行」→コピー
5. **Channel Access Token** を取得:
   - 「Messaging API設定」タブ → 「チャネルアクセストークン（長期）」→「発行」→コピー
6. Webhook URL は **Step 6** でバックエンドをデプロイした後に設定します

---

### Step 5: Python バックエンドのデプロイ（Render）

Render の無料プランを使います（月750時間まで無料）。

#### 5-1. GitHub リポジトリの準備

```bash
cd /Users/as.t/Documents/HealthManager

# .env は絶対にコミットしない！
cp .env.example .env  # 実際の値を記入する用

git init
git add .
git commit -m "initial commit"
```

GitHub でリポジトリを作成し、push:

```bash
git remote add origin https://github.com/<YOUR_USERNAME>/<REPO_NAME>.git
git branch -M main
git push -u origin main
```

#### 5-2. Render でウェブサービスを作成

1. [Render](https://render.com/) にサインアップ（GitHub連携推奨）
2. 「New +」→「Web Service」→対象のリポジトリを選択
3. 設定:
   | 項目 | 値 |
   |------|-----|
   | **Name** | line-health-bot（任意） |
   | **Runtime** | Python 3 |
   | **Build Command** | `pip install -r requirements.txt` |
   | **Start Command** | `uvicorn main:app --host 0.0.0.0 --port $PORT` |
   | **Instance Type** | Free |

4. 「Environment」タブで環境変数を追加:
   | キー | 値 |
   |------|-----|
   | `LINE_CHANNEL_SECRET` | Step 4 で取得した Channel Secret |
   | `LINE_CHANNEL_ACCESS_TOKEN` | Step 4 で取得した Access Token |
   | `GEMINI_API_KEY` | Step 1 で取得したキー |
   | `GAS_ENDPOINT_URL` | Step 3 で取得した GAS URL |

5. 「Create Web Service」をクリック → デプロイ完了を待つ（2〜3分）
6. 発行された URL をメモ（例: `https://line-health-bot.onrender.com`）

---

### Step 6: LINE Webhook URL の設定

1. LINE Developers Console の「Messaging API設定」タブを開く
2. 「Webhook URL」に以下を入力して保存:
   ```
   https://line-health-bot.onrender.com/callback
   ```
3. 「Webhookの利用」を **ON** に切り替える
4. 「検証」ボタンで `{"message":"ok"}` が返ることを確認

---

### Step 7: LINE Bot を友だち追加してテスト

1. 「Messaging API設定」タブのQRコードから Bot を友だち追加
2. LINEで食事内容を送信:

   ```
   昼：牛丼並盛
   ```

   ```
   夜：唐揚げ3個、ご飯1杯、味噌汁
   体重：68.5kg
   ```

3. Bot から **確認プレビュー** が返信され、**Quick Reply ボタン**が表示される

   ```
   📋 以下の内容をスプレッドシートに記録します。よろしいですか？

   📅 日付: 2026/03/08
   🍽️ タイミング: 昼
   🥗 食事内容: 牛丼並盛
   🔥 推定カロリー: 650 kcal
   💡 タンパク質が…（アドバイス）
   [記録する]  [キャンセル]
   ```

4. **「記録する」** をタップ → GASへ書き込み・完了メッセージが返信される
5. **「キャンセル」** をタップ → 記録されずキャンセル確認が返信される 🎉

---

## ローカルでの開発・テスト方法

```bash
cd /Users/as.t/Documents/HealthManager

# 仮想環境の作成と有効化
python3 -m venv .venv
source .venv/bin/activate

# 依存ライブラリのインストール
pip install -r requirements.txt

# 環境変数の設定（.env.example をコピーして実際の値を記入）
cp .env.example .env

# サーバー起動
uvicorn main:app --reload --port 8000
```

LINE からのローカルテストには [ngrok](https://ngrok.com/) を使用:

```bash
# 別ターミナルで
ngrok http 8000
# 発行された https://xxxx.ngrok.io/callback を Webhook URL に設定
```

---

## トラブルシューティング

| 症状 | 原因と対処 |
|------|-----------|
| LINEに返信が来ない | Render のログを確認。Webhook URL が `/callback` まで含まれているか確認 |
| 「署名検証エラー」が出る | `LINE_CHANNEL_SECRET` が正しいか確認 |
| Quick Replyボタンをタップしても反応がない | Render のコールドスタートが原因。少し待って再送信 |
| 「確認待ちのデータがありません」と出る | サーバー再起動でインメモリがクリアされた。食事内容を再送信 |
| スプレッドシートに書き込まれない | GAS の「実行ログ」を確認。`SPREADSHEET_ID` が正しいか確認 |
| Gemini がJSONを返さない | Render のログで Gemini のレスポンスを確認。モデル名を確認 |
| Render で503エラー | 無料プランはアイドル後の初回リクエストが遅い（コールドスタート）。少し待って再送信 |

---

## 環境変数一覧

| 変数名 | 説明 | 取得場所 |
|--------|------|---------|
| `LINE_CHANNEL_SECRET` | LINE署名検証キー | LINE Developers Console |
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE API認証トークン | LINE Developers Console |
| `GEMINI_API_KEY` | Gemini API認証キー | Google AI Studio |
| `GAS_ENDPOINT_URL` | GAS WebアプリURL | GAS デプロイ時に発行 |
