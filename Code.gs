/**
 * LINE Health Manager Bot - Google Apps Script
 *
 * デプロイ方法:
 *   1. このスクリプトをスプレッドシートのコンテナバインドまたはスタンドアロンプロジェクトとして開く
 *   2. SPREADSHEET_ID に対象スプレッドシートのIDを設定する
 *   3. 「デプロイ」>「新しいデプロイ」> 種類「ウェブアプリ」
 *      - 実行ユーザー: 自分
 *      - アクセス: 全員（匿名ユーザーを含む）
 *   4. 発行されたURLを PYTHON バックエンドの GAS_ENDPOINT_URL に設定する
 */

// ── 設定 ──────────────────────────────────────────────────────────────────
const SPREADSHEET_ID = "1YcGjvl1ijYIF2YeoCihEOS_MQPeajSFCUVgrwIf177o"; // ← スプレッドシートのIDに変更
const SHEET_NAME = "健康記録";

// スプレッドシートのヘッダー行（初回実行時に自動生成）
const HEADERS = ["日付", "タイミング", "食事内容", "カロリー(kcal)", "体重(kg)", "メモ", "アドバイス", "記録日時"];


// ── doPost ────────────────────────────────────────────────────────────────
/**
 * PythonバックエンドからのPOSTリクエストを受け取り、スプレッドシートに追記する
 * @param {GoogleAppsScript.Events.DoPost} e
 */
function doPost(e) {
  try {
    // JSONパース
    const payload = JSON.parse(e.postData.contents);

    // バリデーション（必須フィールド）
    const required = ["date", "timing", "food", "calories"];
    for (const field of required) {
      if (payload[field] === undefined || payload[field] === null) {
        return buildResponse(400, { error: `Missing required field: ${field}` });
      }
    }

    // シートを取得（なければ作成）
    const sheet = getOrCreateSheet();

    // 行データを組み立てる（HEADERSの順番と一致させる）
    const now = Utilities.formatDate(new Date(), "Asia/Tokyo", "yyyy/MM/dd HH:mm:ss");
    const row = [
      payload.date,
      payload.timing,
      payload.food,
      Number(payload.calories),
      payload.weight !== null && payload.weight !== undefined ? Number(payload.weight) : "",
      payload.memo || "",
      payload.advice || "",
      now,
    ];

    sheet.appendRow(row);
    Logger.log("Appended row: %s", JSON.stringify(row));

    return buildResponse(200, { status: "ok", recorded_at: now });

  } catch (err) {
    Logger.log("doPost error: %s", err.toString());
    return buildResponse(500, { error: err.toString() });
  }
}


// ── doGet (ヘルスチェック用) ───────────────────────────────────────────────
function doGet(e) {
  return buildResponse(200, { status: "ok", message: "LINE Health Manager GAS is running." });
}


// ── Helpers ───────────────────────────────────────────────────────────────
/**
 * シートを取得する。存在しない場合は作成してヘッダーを追加する。
 */
function getOrCreateSheet() {
  const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  let sheet = ss.getSheetByName(SHEET_NAME);

  if (!sheet) {
    sheet = ss.insertSheet(SHEET_NAME);
    sheet.appendRow(HEADERS);

    // ヘッダー行のスタイルを設定
    const headerRange = sheet.getRange(1, 1, 1, HEADERS.length);
    headerRange.setBackground("#1a73e8");
    headerRange.setFontColor("#ffffff");
    headerRange.setFontWeight("bold");
    sheet.setFrozenRows(1);

    // 列幅を調整
    sheet.setColumnWidth(1, 110);  // 日付
    sheet.setColumnWidth(2, 80);   // タイミング
    sheet.setColumnWidth(3, 200);  // 食事内容
    sheet.setColumnWidth(4, 120);  // カロリー
    sheet.setColumnWidth(5, 90);   // 体重
    sheet.setColumnWidth(6, 200);  // メモ
    sheet.setColumnWidth(7, 300);  // アドバイス
    sheet.setColumnWidth(8, 160);  // 記録日時

    Logger.log("Created new sheet: %s", SHEET_NAME);
  }

  return sheet;
}

/**
 * JSON レスポンスを組み立てる
 */
function buildResponse(statusCode, data) {
  const output = ContentService.createTextOutput(JSON.stringify(data));
  output.setMimeType(ContentService.MimeType.JSON);
  // GASのウェブアプリはHTTPステータスコードを直接制御できないが、
  // ボディにステータスを含めることでクライアント側で判別可能にする
  return output;
}
