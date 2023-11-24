
import json
from multiprocessing import Process, Queue
from os import path, sep, mkdir, makedirs, getcwd, chdir
import subprocess
import sys
import concurrent.futures
import psutil
if 'BASE_DIR' not in globals():
    BASE_DIR = path.dirname(__file__); 
if getcwd() != BASE_DIR:
    chdir(BASE_DIR)     # 如果cwd不是文件根目录，就切换过去。这是为了用相对目录加载模型文件，以避免中文路径问题
import rich
from rich.console import Console 
console = Console(highlight=False)

with console.status("载入模块中…", spinner="bouncingBall", spinner_style="yellow"):
    from pathlib import Path
    import time
    import asyncio
    import re
    from datetime import timedelta
    from dataclasses import dataclass

    import numpy as np
    import websockets
    import sherpa_onnx
    from funasr_onnx import CT_Transformer

    import jieba
    import logging
    jieba.setLogLevel(logging.INFO)
    import signal
    import sys
console.print('[green4]模块加载完成', end='\n\n')


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
    num_threads = 3
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
    console.print(f'项目地址：[cyan underline]https://github.com/HaujetZhao/CapsWriter-Offline', end='\n\n')



def recognize(data):
    frames_per_chunk = int(args.sample_rate * 60)  # 以 60 秒为一段
    streams = []
    segments_raw = []
    samples_processed = 0
    index = 0

    while index < len(data):

        # 每帧数据 2Byte
        chunk = data[index : index + frames_per_chunk * 2]
        index += frames_per_chunk * 2
        
        # 读取音频片段
        samples = np.frombuffer(chunk, dtype=np.int16)
        samples = samples.astype(np.float32) / 32768
        
        # 划分片段时间
        segment = Segment(
            start = samples_processed / args.sample_rate,
            duration = frames_per_chunk / args.sample_rate,
        )
        segments_raw.append(segment)
        samples_processed += frames_per_chunk

        stream = recognizer.create_stream()
        stream.accept_waveform(args.sample_rate, samples)
        streams.append(stream)
            
    # 统一识别
    recognizer.decode_streams(streams)

    
    timestamps = [t + seg.start for seg, stream in zip(segments_raw, streams) 
                                    for t in stream.result.timestamps]
    tokens = [token for stream in streams 
                        for token in stream.result.tokens]
    # 带有标点的文本
    # text = ''.join(tokens)
    text = punc_model(''.join(tokens))[0]  
    
    # 发送回去
    message = {'timestamps': timestamps, 
                            'tokens': tokens, 
                            'text': text}
    
    return message 

def init_recognizer(queue_in: Queue, queue_out: Queue):
    global recognizer
    global punc_model

    # 首先，重定向 ctrl-c 行为
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
    console.print(f'加载耗时 {time.time() - t1 :.2f}s', end='\n\n')
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
            print(f'收到音频，时长 {len(data) / args.sample_rate / 2}s，开始识别')

            # 阻塞型任务，在另一进程处理
            queue_in.put(data)
            message = await asyncio.to_thread(queue_out.get)

            print(f'识别完成，时间戳、分词结果已返回，合并文本：{message["text"]}')
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
