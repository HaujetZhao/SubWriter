
import json
from multiprocessing import Process, Queue
from os import path, sep, mkdir, makedirs, getcwd, chdir
import sys
if 'BASE_DIR' not in globals():
    BASE_DIR = path.dirname(__file__); 
if getcwd() != BASE_DIR:
    chdir(BASE_DIR)     # 如果cwd不是文件根目录，就切换过去。这是为了用相对目录加载模型文件，以避免中文路径问题
import rich
from rich.console import Console 
console = Console(highlight=False)

import time
import sys
import re
import asyncio
from pathlib import Path
from datetime import timedelta
from dataclasses import dataclass

import websockets

from util import chinese_itn, format_tools



# ============================全局变量和检查区====================================

addr = '0.0.0.0'
port = '6008'

model_dir = Path() / 'models'
paraformer_path = Path() / 'models' / 'paraformer' / 'model.int8.onnx'
tokens_path = Path() / 'models' / 'paraformer' /  'tokens.txt'

punc_model_dir = Path() / 'models' /  'punc_ct' 

class args:
    paraformer = f'{paraformer_path}' 
    tokens = f'{tokens_path}'
    num_threads = 6
    sample_rate = 16000
    feature_dim = 80
    decoding_method = 'greedy_search'
    debug = False



# ========================================================================

@dataclass
class Segment:
    start: float
    duration: float
    text: str = ""

    @property
    def end(self):
        return self.start + self.duration

    def __str__(self):
        s = f"{timedelta(seconds=self.start)}"
        s += " --> "
        s += f"{timedelta(seconds=self.end)}"
        s = s.replace(".", ",")
        s += "\n"
        s += self.text
        return re.sub(r'(,\d{3})\d+', r'\1', s)

def signal_handler(sig, frame):
    print("收到中断信号 Ctrl+C，退出程序")
    sys.exit(0)

def splash():
    console.line(2)
    console.rule('[bold #d55252]SubWriter Offline Server'); console.line()
    console.print(f'当前基文件夹：[cyan underline]{BASE_DIR}', end='\n\n')
    for path in (paraformer_path, tokens_path, punc_model_dir,):
        if path.exists(): continue
        console.print(f'''
        未能找到模型文件 

        未找到：{path}

        本服务端需要 paraformer 模型和 punc_ct 模型，
        请下载模型并放置到： {model_dir} 

        ''', style='bright_red'); input('按回车退出'); sys.exit()
    console.print(f'绑定的服务地址：[cyan underline]{addr}:{port}', end='\n\n')
    console.print(f'项目地址：[cyan underline]https://github.com/HaujetZhao/SubWriter', end='\n\n')


def recognize(data):
    sample_rate = args.sample_rate
    chunk_seconds = 30      # 以多少秒为一段
    overlap_seconds = 2     # 两段之间重叠多少秒
    frames_per_chunk = int(sample_rate * chunk_seconds)  

    index = 0
    timestamps = []
    tokens = []
    progress = 0  # 记录已经识别了多少秒
    while index < len(data):

        # 每帧数据 2Byte
        start = index
        end = index + (frames_per_chunk * 2) + (overlap_seconds * sample_rate * 2)
        chunk = data[start : end]
        if not chunk: break
        index += frames_per_chunk * 2
        
        # 转换音频片段
        samples = np.frombuffer(chunk, dtype=np.int16)
        samples = samples.astype(np.float32) / 32768
        
        # 识别
        stream = recognizer.create_stream()
        stream.accept_waveform(args.sample_rate, samples)
        recognizer.decode_stream(stream); 

        # 粗去重
        for i, timestamp in enumerate(stream.result.timestamps, start=1):
            if timestamp > overlap_seconds / 2: 
                m = i; break 
        for i, timestamp in enumerate(stream.result.timestamps, start=1):
            n = i
            if timestamp > chunk_seconds + overlap_seconds / 2: break 
        if start == 0: m = 0
        if index >= len(data): n = len(stream.result.timestamps)

        # 细去重
        if tokens and tokens[-2:] == stream.result.tokens[m:n][:2]: m += 2
        elif tokens and tokens[-1:] == stream.result.tokens[m:n][:1]: m += 1

        # 收集结果
        timestamps += [t + progress for t in stream.result.timestamps[m:n]]
        tokens += [token for token in stream.result.tokens[m:n]]

        # 更新进度
        progress += chunk_seconds
        print(f'\r识别进度：{progress}s', end='', flush=True)

    # token 合并为文本
    text = ' '.join(tokens).replace('@@ ', '')
    text = re.sub('([^a-zA-Z0-9]) (?![a-zA-Z0-9])', r'\1', text)

    
    text = format_tools.adjust_space(text)      # 调空格
    try: text = punc_model(text)[0]             # 加标点
    except: ...
    text = chinese_itn.chinese_to_num(text)     # 转数字
    text = format_tools.adjust_space(text)      # 调空格

    

    
    # 发送回去
    message = {'timestamps': timestamps, 
                            'tokens': tokens, 
                            'text': text}
    
    return message 

def init_recognizer(queue_in: Queue, queue_out: Queue):
    global np
    global recognizer
    global punc_model

    with console.status("载入模块中…", spinner="bouncingBall", spinner_style="yellow"):
        import numpy as np
        import sherpa_onnx
        from funasr_onnx import CT_Transformer
    console.print('[green4]模块加载完成', end='\n\n')

    # 关闭 jieba 的 debug
    import jieba
    import logging
    jieba.setLogLevel(logging.INFO)

    # 重定向 ctrl-c 行为
    import signal
    signal.signal(signal.SIGINT, signal_handler)
    

    rich.print('[yellow]语音模型载入中', end='\r'); t1 = time.time()
    recognizer = sherpa_onnx.OfflineRecognizer.from_paraformer(
        paraformer=args.paraformer,
        tokens=args.tokens,
        num_threads=args.num_threads,
        sample_rate=args.sample_rate,
        feature_dim=args.feature_dim,
        decoding_method=args.decoding_method,
        debug=args.debug,)
    rich.print(f'[green4]语音模型载入完成', end='\n');print('')

    rich.print('[yellow]标点模型载入中', end='\r')
    punc_model = CT_Transformer(punc_model_dir, quantize=True)
    console.print(f'[green4]标点模型载入完成', end='\n\n')

    console.print(f'模型加载耗时 {time.time() - t1 :.2f}s', end='\n\n')
    queue_out.put(True) # 通知主进程加载完了

    while True:
        data = queue_in.get()       # 从队列中获取任务消息
        message = recognize(data)   # 执行识别
        queue_out.put(message)      # 返回结果

async def ws_serve(websocket, path):
    global loop
    global message
    global queue_in, queue_out

    console.print(f'接客了：{websocket}', style='yellow')

    try:
        async for data in websocket:
            duration_audio = len(data) / args.sample_rate / 2
            print(f'收到音频，时长 {duration_audio:.1f}s，开始识别'); t1 = time.time()

            # 阻塞型任务，在另一进程处理
            queue_in.put(data)
            message = await asyncio.to_thread(queue_out.get)
            duration_recognize = time.time()-t1

            print(f'时间戳、分词结果已返回，合并文本：\n    {message["text"]}')
            print(f'识别耗时：{duration_recognize:.1f}s')
            print(f'RTF：{duration_recognize / duration_audio:.3f}')
            await websocket.send(json.dumps(message))

    except websockets.ConnectionClosed:
        console.print("ConnectionClosed...", )
    except websockets.InvalidState:
        console.print("InvalidState...")
    except Exception as e:
        console.print("Exception:", e)


async def main():
    global args, punc_model_dir
    global loop; loop = asyncio.get_event_loop()
    global queue_in, queue_out

    # 显示欢迎信息
    splash()

    # 识别部分是阻塞的，在子进程中执行，用两个队列传递消息
    queue_in = Queue()
    queue_out = Queue()
    recognize_process = Process(target=init_recognizer, args=(queue_in, queue_out), daemon=True)
    recognize_process.start()
    queue_out.get() # 等待新进程加载完成

    console.rule('[green3]开始服务'); console.line()
    start_server = websockets.serve(ws_serve, 
                                addr, 
                                port, 
                                subprotocols=["binary"], 
                                max_size=None)
    try:
        await start_server
    except OSError as e:            # 有时候可能会因为端口占用而报错，捕获一下
        console.print(f'出错了：{e}', style='bright_red'); console.input('...')
        sys.exit()
    await asyncio.Event().wait()    # 持续运行


def init():
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print('再见！')
        sys.exit()
        
if __name__ == "__main__":
    init()
