终于把自己的转字幕程序写好了。服务端运行 sherpa-onnx 载入 Paraformer 模型（载入花6秒），以及阿里的 large 标点onnx模型（载入花50秒），客户端把音视频转为 wav，用 websockets 发给服务端，服务端将音频以 60 秒分段，分别进行识别，得到字级时间戳，全部识别完成后合并，用标点模型加上标点，将合并文本、tokens、timestamps 全返回给客户端。客户端根据字级时间戳，和标点分句，生成分割良好的 srt 字幕。最后，保存4个文件，分别是：srt字幕，每行一句的txt，有标点的整段txt，字级时间戳json。

由于 vad 有时会把一些句子开头或末尾错误的截去一小段，没有使用 vad，实际错字率更低了。由于每 60s 一段，段数更小，识别速度比使用 vad 分成好多段还要快一倍。

之所以分成服务端、客户端，就是因为载入模型非常慢，要近一分钟。

转录两个小时的音频，花了380秒，rtf 0.06，比 whisper 快了不少。

下载标点模型：

```
git clone https://www.modelscope.cn/damo/punc_ct-transformer_cn-en-common-vocab471067-large-onnx.git models/punc_ct
```

下载语音识别模型：

```
git clone https://huggingface.co/csukuangfj/sherpa-onnx-paraformer-zh-2023-09-14 models/paraformer
```