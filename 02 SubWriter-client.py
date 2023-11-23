# coding: utf-8

import json
import os
import sys
import platform

import typer
if platform.system() == 'Darwin' and os.getuid() != 0:
    print('在 MacOS 上需要以管理员启动客户端才能监听键盘活动，请 sudo 启动')
    input('按回车退出'); sys.exit()

from os import path, sep, makedirs, chmod
if 'BASE_DIR' not in globals():
    BASE_DIR = path.dirname(__file__); 
import rich.status
from rich.console import Console 
from rich.markdown import Markdown
from rich.theme import Theme
my_theme = Theme({'markdown.code':'cyan', 'markdown.item.number':'yellow'})
console = Console(highlight=False, soft_wrap=False, theme=my_theme)
console.line(2)
console.rule('[bold #d55252]SubWriter Offline Client'); console.line()
console.print(f'当前基文件夹：[cyan underline]{BASE_DIR}', end='\n\n')

with console.status("载入模块中…", spinner="bouncingBall", spinner_style="yellow"):
    from pathlib import Path
    import time
    import re
    import wave
    import asyncio
    import subprocess

    import websockets

    from util import srt_from_txt
console.print('[green4]模块加载完成', end='\n\n')




# ============================全局变量和检查区====================================

addr = '127.0.0.1'          # Server 地址
port = '6008'               # Server 端口

# ========================================================================



async def main(files: list[Path]):
    websocket = await websockets.connect(f"ws://{addr}:{port}", max_size=None)

    for file in files:
        print(f'\n处理文件：{file}')
        srt_filename = Path(file).with_suffix(".srt")
        json_filename = Path(file).with_suffix(".json")
        txt_filename = Path(file).with_suffix(".txt")
        merge_filename = Path(file).with_suffix(".merge.txt")

        ffmpeg_cmd = [
            "ffmpeg",
            "-i", file,
            "-f", "s16le",
            "-acodec", "pcm_s16le",
            "-ac", "1",
            "-ar", "16000",
            "-",
            ]
        process = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        data = process.stdout.read()

        await websocket.send(data)
        print(f'data has sent'); t1 = time.time()
        message = await websocket.recv()
        message = json.loads(message)
        text_merge = message['text']
        text_split = re.sub('[，。]', '\n', text_merge)
        timestamps = message['timestamps']
        tokens = message['tokens']

        with open(merge_filename, "w", encoding="utf-8") as f:
            f.write(text_merge)
        with open(txt_filename, "w", encoding="utf-8") as f:
            f.write(text_split)
        with open(json_filename, "w", encoding="utf-8") as f:
            json.dump({'timestamps': timestamps, 'tokens': tokens}, f, ensure_ascii=False)
        srt_from_txt.one_task(txt_filename)
        print(f'处理完成，耗时 {time.time()-t1:.2f}s')
    






def init(files: list[Path]):
    try:
        asyncio.run(main(files))
    except KeyboardInterrupt:
        console.print(f'再见！')
        sys.exit()


if __name__ == '__main__':
    typer.run(init)
        