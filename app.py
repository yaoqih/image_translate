#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
商用图文翻译中台
功能：批量上传 -> Gemini 2.5 Flash Image Preview 翻译 -> 批量下载，持久化使用日志
依赖：pip install -U gradio requests pillow
API Key：可在界面输入或通过环境变量 GEMINI_API_KEY 提供
"""
import os
import base64
import json
import mimetypes
import tempfile
import zipfile
import time
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Tuple, Optional, Any

import requests
import gradio as gr

GEMINI_URL = "https://yunwu.ai/v1beta/models/gemini-2.5-flash-image-preview:generateContent"
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "outputs"
EXPORTS_DIR = BASE_DIR / "exports"
DB_PATH = DATA_DIR / "usage.sqlite3"

for p in (DATA_DIR, OUTPUT_DIR, EXPORTS_DIR):
    p.mkdir(parents=True, exist_ok=True)

LANGUAGE_OPTIONS = [
    "简体中文",
    "英语",
    "日语",
    "韩语",
    "德语",
    "法语",
    "西班牙语",
    "俄语",
    "葡萄牙语",
    "阿拉伯语",
    "意大利语",
    "泰语",
    "越南语",
    "印尼语",
]

def guess_mime_type(file_path: str) -> str:
    mt, _ = mimetypes.guess_type(file_path)
    if mt is None:
        return "image/jpeg"
    if not mt.startswith("image/"):
        return "image/jpeg"
    return mt

def image_file_to_b64(file_path: str) -> Tuple[str, str]:
    with open(file_path, "rb") as f:
        data = f.read()
    b64 = base64.b64encode(data).decode("utf-8")
    mime = guess_mime_type(file_path)
    return mime, b64

def extract_image_from_response(payload: Any) -> Optional[Tuple[str, str]]:
    def walk(node: Any) -> Optional[Tuple[str, str]]:
        if isinstance(node, dict):
            if "inline_data" in node and isinstance(node["inline_data"], dict):
                inline = node["inline_data"]
                data = inline.get("data")
                mt = inline.get("mime_type", "image/png")
                if isinstance(data, str):
                    return mt, data
            if "data" in node and isinstance(node["data"], str) and len(node["data"]) > 100:
                return node.get("mime_type", "image/png"), node["data"]
            for v in node.values():
                found = walk(v)
                if found:
                    return found
        elif isinstance(node, list):
            for item in node:
                found = walk(item)
                if found:
                    return found
        return None
    return walk(payload)

def call_gemini_edit(image_b64: str, mime_type: str, prompt: str, api_key: str, timeout: int = 120) -> Tuple[bytes, str]:
    headers = {
        "x-goog-api-key": api_key,
        "Content-Type": "application/json",
    }
    body = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": mime_type, "data": image_b64}},
                ]
            }
        ]
    }
    resp = requests.post(GEMINI_URL, headers=headers, data=json.dumps(body), timeout=timeout)
    if resp.status_code != 200:
        try:
            err = resp.json()
        except Exception:
            err = {"error_text": resp.text}
        raise RuntimeError(f"Gemini API error: {resp.status_code} {err}")
    payload = resp.json()
    found = extract_image_from_response(payload)
    if not found:
        raise RuntimeError(f"No image data found in response: {json.dumps(payload)[:800]}...")
    out_mime, out_b64 = found
    try:
        out_bytes = base64.b64decode(out_b64)
    except Exception as e:
        raise RuntimeError(f"Failed to decode base64 image: {e}")
    return out_bytes, out_mime

def ensure_output_dir() -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = OUTPUT_DIR / f"gemini_edits_{ts}"
    base.mkdir(parents=True, exist_ok=True)
    return base

def ext_from_mime(mime: str) -> str:
    mapping = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "image/heic": ".heic",
    }
    return mapping.get(mime.lower(), ".png")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                language TEXT NOT NULL,
                file_count INTEGER NOT NULL,
                success_count INTEGER DEFAULT 0,
                error_count INTEGER DEFAULT 0,
                zip_path TEXT,
                duration_ms INTEGER DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS file_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                ts TEXT NOT NULL,
                filename TEXT NOT NULL,
                status TEXT NOT NULL,
                out_mime TEXT,
                message TEXT,
                FOREIGN KEY(session_id) REFERENCES sessions(id)
            )
        """)
        conn.commit()
    finally:
        conn.close()

def open_db():
    return sqlite3.connect(DB_PATH, timeout=30)

def log_session_start(language: str, file_count: int) -> int:
    conn = open_db()
    try:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur = conn.cursor()
        cur.execute("INSERT INTO sessions (ts, language, file_count) VALUES (?, ?, ?)", (ts, language, file_count))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()

def log_session_finalize(session_id: int, success_count: int, error_count: int, zip_path: str, duration_ms: int):
    conn = open_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE sessions SET success_count=?, error_count=?, zip_path=?, duration_ms=? WHERE id=?",
            (success_count, error_count, zip_path, duration_ms, session_id),
        )
        conn.commit()
    finally:
        conn.close()

def log_file_result(session_id: int, filename: str, status: str, out_mime: Optional[str], message: str):
    conn = open_db()
    try:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO file_logs (session_id, ts, filename, status, out_mime, message) VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, ts, filename, status, out_mime or "", message),
        )
        conn.commit()
    finally:
        conn.close()

def get_recent_logs(limit: int = 50) -> List[List[str]]:
    conn = open_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, ts, language, file_count, success_count, error_count, IFNULL(zip_path,'') , duration_ms FROM sessions ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        rows = cur.fetchall()
        table = []
        for r in rows:
            table.append([str(r[0]), r[1], r[2], str(r[3]), str(r[4]), str(r[5]), r[6], str(r[7])])
        return table
    finally:
        conn.close()

def export_logs_csv() -> str:
    conn = open_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, ts, language, file_count, success_count, error_count, IFNULL(zip_path,''), duration_ms FROM sessions ORDER BY id DESC")
        rows = cur.fetchall()
        csv_path = EXPORTS_DIR / f"usage_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        with open(csv_path, "w", encoding="utf-8") as f:
            f.write("session_id,ts,language,file_count,success_count,error_count,zip_path,duration_ms\n")
            for r in rows:
                line = f"{r[0]},{r[1]},{r[2]},{r[3]},{r[4]},{r[5]},{r[6]},{r[7]}\n"
                f.write(line)
        return str(csv_path)
    finally:
        conn.close()

def process_images(files: List[Any], target_language: str, api_key_ui: str, progress=gr.Progress()) -> Tuple[List[Tuple[str, str]], str, str]:
    init_db()
    logs: List[str] = []
    gallery_items: List[Tuple[str, str]] = []
    zip_path: Optional[Path] = None
    prompt = (
        f"请将海报中的可读文本专业翻译为{target_language}，保持版式、风格与图像一致。"
        "商品本体、商标、包装上的文字和logo必须保持原样，不要翻译。"
        "输出为合成后的完整海报图像。"
    )
    if not files or len(files) == 0:
        return [], "", "请先上传至少一张图片。"
    api_key = (api_key_ui or "").strip() or os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return [], "", "缺少 GEMINI_API_KEY。请在界面中输入或设置环境变量。"
    out_dir = ensure_output_dir()
    total = len(files)
    session_id = log_session_start(target_language, total)
    t0 = time.time()
    success_count = 0
    error_count = 0
    progress(0, desc=f"开始处理 {total} 张图片...")
    for idx, f in enumerate(files, start=1):
        if isinstance(f, dict) and "name" in f:
            in_path = f["name"]
        elif hasattr(f, "name"):
            in_path = getattr(f, "name")
        else:
            in_path = str(f)
        in_path = str(in_path)
        filename = Path(in_path).name
        try:
            mime, img_b64 = image_file_to_b64(in_path)
            progress((idx - 1) / total, desc=f"处理中：{filename}")
            bytes_out, out_mime = call_gemini_edit(img_b64, mime, prompt, api_key)
            ext = ext_from_mime(out_mime)
            out_file = out_dir / f"{Path(filename).stem}_translated{ext}"
            with open(out_file, "wb") as wf:
                wf.write(bytes_out)
            gallery_items.append((str(out_file), f"{filename} ✅"))
            logs.append(f"[OK] {filename} -> {out_file.name} ({out_mime})")
            log_file_result(session_id, filename, "OK", out_mime, "转换成功")
            success_count += 1
        except Exception as e:
            msg = f"[ERR] {filename} -> {e}"
            logs.append(msg)
            log_file_result(session_id, filename, "ERR", None, str(e))
            error_count += 1
        progress(idx / total, desc=f"已完成 {idx}/{total}")
    out_files = [p for p, _ in gallery_items]
    if len(out_files) > 0:
        zip_name = out_dir / "translated_images.zip"
        with zipfile.ZipFile(zip_name, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for p in out_files:
                zf.write(p, arcname=Path(p).name)
        zip_path = zip_name
        logs.append(f"打包完成: {zip_path}")
        zip_path_str = str(zip_path)
    else:
        zip_path_str = ""
    duration_ms = int((time.time() - t0) * 1000)
    log_session_finalize(session_id, success_count, error_count, zip_path_str, duration_ms)
    return gallery_items, zip_path_str, "\n".join(logs)

init_db()
with gr.Blocks(theme=gr.themes.Soft(), fill_width=True, title="商用图文翻译中台") as demo:
    gr.Markdown(
        "### 商用图文翻译中台\n"
    )
    with gr.Row():
        target_language = gr.Dropdown(label="目标语言", choices=LANGUAGE_OPTIONS, value="英语")
        api_key_inp = gr.Textbox(label="GEMINI API Key", type="password", value="sk-mfWjPViGZfZEjO8j3xO8MmLIKCV1rG3mVHh9IRtVFh5iKdRx")
    files_in = gr.Files(label="上传图片（可多选）", file_count="multiple", file_types=["image"])
    with gr.Row():
        go_btn = gr.Button("开始处理", variant="primary")
        refresh_btn = gr.Button("刷新日志")
        export_btn = gr.Button("导出日志CSV")
    with gr.Row():
        gallery_out = gr.Gallery(label="编辑结果预览", columns=[3], height=400)
    zip_out = gr.File(label="下载所有（ZIP）")
    csv_out = gr.File(label="下载日志（CSV）")
    log_out = gr.Textbox(label="处理日志", lines=10)
    logs_table = gr.Dataframe(
        headers=["会话ID","时间","语言","文件数","成功数","错误数","ZIP路径","耗时ms"],
        label="历史会话（持久化）",
        interactive=False,
    )
    def refresh_logs():
        return get_recent_logs(50)
    def export_logs():
        return export_logs_csv()
    go_btn.click(process_images, inputs=[files_in, target_language, api_key_inp], outputs=[gallery_out, zip_out, log_out])
    refresh_btn.click(refresh_logs, None, logs_table)
    export_btn.click(export_logs, None, csv_out)

if __name__ == "__main__":
    demo.queue().launch()