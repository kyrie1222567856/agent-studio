# ComfyUI 接入指南（漫剧模块 · comfyui 自动出图模式）

按本指南配置后，任务二的生成任务可选 **comfyui 模式**：在网页里点「提交到 ComfyUI」→ 系统经 HTTP API 把关键帧 Prompt 填入你的工作流模板并提交 → 点「查询结果」自动取回出图并落盘为任务结果，随后照常走多模态评价 → 修改重跑 → ◇采用。

## 一、安装并启动 ComfyUI（Windows）

1. 到 GitHub 的 comfyanonymous/ComfyUI Releases 页面下载 **ComfyUI_windows_portable**（N 卡选 nvidia 版），解压到任意目录（路径不要含中文）。
2. 下载一个 SDXL 底模（如 `sd_xl_base_1.0.safetensors`，可从 HuggingFace / liblib 获取），放入 `ComfyUI/models/checkpoints/`。
3. 双击 `run_nvidia_gpu.bat`（无独显用 `run_cpu.bat`，很慢）。启动成功后浏览器访问 `http://127.0.0.1:8188` 能看到节点界面即可。

> Agent Studio 与 ComfyUI 在同一台电脑时无需任何额外参数；若 ComfyUI 在另一台机器，用 `--listen 0.0.0.0` 启动并把 .env 里的地址换成那台机器的 IP。

## 二、准备"API 格式"工作流模板

方式 A（最快）：直接用源码根目录附带的 `comfyui_workflow.example.json` —— 一个 SDXL 文生图工作流，704×1216（≈9:16 竖屏），已埋好占位符。前提是你的 checkpoints 目录里有 `sd_xl_base_1.0.safetensors`；若你的底模文件名不同，把模板里 `ckpt_name` 改成你的文件名即可。

方式 B（用你自己的工作流）：
1. 在 ComfyUI 里把工作流调到满意（底模、LoRA、分辨率 9:16、采样器等）。
2. 右上角 Settings（齿轮）→ 打开 **Dev mode**；然后菜单里用 **Save (API Format)** 导出 JSON（注意必须是 API Format，不是普通 Save）。
3. 打开导出的 JSON，找到正向提示词的 `CLIPTextEncode` 节点，把它的 `"text"` 值整个换成 `"__PROMPT__"`；负向节点的 `"text"` 换成 `"__NEGATIVE__"`。保存。

系统提交时会把网页里该任务的英文 Prompt / 负面词填进这两个占位符，其余节点原样执行——所以底模、LoRA、参考图 IPAdapter 等都按你模板里的来，这正好符合任务书"把成功的 ComfyUI 工作流存成模板/JSON 做版本化迭代"的建议。

## 三、配置 Agent Studio

编辑 `.env`（两行都要）：

```ini
COMFYUI_URL=http://127.0.0.1:8188
COMFYUI_WORKFLOW=./comfyui_workflow.example.json   # 或你自己的 API 格式模板路径
```

重启 uvicorn。验证：总览页「运行状态」里 **ComfyUI 自动出图** 显示 ● 已配置；漫剧生成任务的模式下拉出现「comfyui · 自动出图」。

## 四、使用流程

1. 镜头确认后，模式选 **comfyui**，点「编排关键帧任务」→ 生成 Prompt。
2. 点「提交到 ComfyUI」（任务转为"已提交 ComfyUI"）。
3. 出图需要几秒到几十秒，点「查询结果」拉取；完成后图片自动显示为任务结果。
4. 照常「多模态一致性评价」→ 不满意则「修改 Prompt → 新版本」再次提交，形成版本链。

## 五、常见问题

| 现象 | 原因与处理 |
|---|---|
| 模式下拉没有 comfyui | .env 两个变量没配全 / 模板文件路径不存在；改后需重启 uvicorn |
| 提交报 502 | ComfyUI 没启动或地址端口不对；先在浏览器确认 8188 可访问 |
| 查询一直 running | 首次运行要加载底模，等 1-2 分钟再查；或看 ComfyUI 控制台是否在跑 |
| 状态变 failed | 多为模板问题：ckpt_name 文件不存在 / 占位符没替换 / 不是 API Format 导出；看 ComfyUI 控制台报错 |
| 想用图生图/IPAdapter 保持角色一致 | 在你的工作流里配置好参考图节点后按方式 B 导出即可；系统只替换文字 Prompt，其余节点不动 |

> 说明：comfyui 模式当前针对**关键帧图像**；视频段生成仍走 external（即梦/Kling/Seedance 人工执行回传），符合任务书"外部工具完成生成环节"的定位。
