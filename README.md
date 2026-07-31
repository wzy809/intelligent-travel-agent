# 智能旅行规划 Agent

一个面向年轻自由行用户的 AI 旅行规划产品原型，聚焦“收藏了很多地点，但不知道如何整理成可执行路线”的真实痛点。

用户可以输入旅行想法，或从小红书、抖音、携程等平台复制地点/链接/截图。系统会通过 Agent 式追问补齐关键信息，并生成可解释、可修改的每日旅行方案。

## 项目定位

本项目不是泛泛生成攻略的聊天机器人，而是一个“从收藏地点到可执行路线”的智能旅行规划 Agent。

核心目标：

- 帮用户整理零散收藏地点。
- 保留用户标记的必去地点。
- 主动识别相似景点、绕路、过满、预约和价格风险。
- 输出 1-3 套可比较的旅行方案。
- 支持用户继续对话修改方案。

## 目标用户

20-35 岁年轻自由行用户。

他们通常会在小红书、抖音、携程等平台收藏大量旅行内容，但在真正出行前需要花很多时间做筛选、路线拼接和取舍。

## 核心流程

```text
用户输入旅行想法 / 收藏地点
  ↓
Agent 创建旅行规划会话
  ↓
逐步追问关键信息
  ↓
地点识别与补全
  ↓
路线诊断
  ↓
生成 1-3 套路线方案
  ↓
用户对话修改
  ↓
确认最终行程
```

## 功能亮点

- App 式轻量交互页面。
- 支持文本、截图、链接三种导入入口。
- 逐步追问：城市、日期、到达/离开时间、同行人数、预算、必去地点、节奏、交通、酒店区域。
- 地点补全：标准名称、地址、类型、营业时间、价格、建议游玩时长、预约、置信状态。
- 方案生成：路线最顺版、松弛体验版、高效打卡版。
- 方案修改：支持“第二天太累了”“预算降一点”“不要早起”“高效打卡”等自然语言修改。
- 置信状态：已确认 / 待确认 / 可能变化。
- Demo Mode + LLM Mode：无 API Key 也可演示，有 DeepSeek API Key 时可调用 DeepSeek 生成真实方案。

## 项目结构

```text
intelligent-travel-agent/
  server.py
  requirements.txt
  public/
    index.html
    styles.css
    app.js
  docs/
    PRD.md
    portfolio.md
  screenshots/
    README.md
```

## 快速运行

当前项目可以不配置 API Key，直接运行 Demo Mode。

```powershell
python server.py
```

运行后会自动打开：

```text
http://127.0.0.1:8000
```

如果浏览器没有自动打开，可以手动访问上面的地址。

## 启用 LLM Mode

如果希望调用真实 DeepSeek API 生成路线，先创建 `.env` 文件：

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

然后打开 `.env`，把 `DEEPSEEK_API_KEY` 改成你的真实 Key：

```text
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=你的_deepseek_api_key
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_THINKING=disabled
USE_LLM_EXTRACTION=auto
```

最后启动：

```powershell
python server.py
```

默认模型：

```text
deepseek-v4-flash
```

说明：如果未配置 DeepSeek API Key 或调用失败，系统会在页面中显示错误原因，不再返回本地兜底路线。

## API 概览

```text
GET  /api/health
POST /api/import/text
POST /api/import/image
POST /api/import/link
POST /api/places/enrich
POST /api/sessions
GET  /api/sessions/{session_id}
POST /api/sessions/{session_id}/answers
POST /api/sessions/{session_id}/plans
POST /api/sessions/{session_id}/revise
POST /api/sessions/{session_id}/confirm
```

## Agent 设计原则

1. 用户需求优先：必去地点默认保留。
2. 真实可执行优先：考虑日期、首尾日时间、路线顺路性、营业时间、价格、预约。
3. 主动指出不合理：过满、绕路、预算超出、相似景点重复都要提示。
4. 轻微问题直接优化，重大冲突必须确认。
5. 不确定信息必须展示置信状态。

## 文档

- [PRD](docs/PRD.md)
- [面试作品集说明](docs/portfolio.md)

## 后续迭代

- 接入地图 POI，实现真实坐标和距离判断。
- 接入交通路线 API，计算真实步行、地铁、打车耗时。
- 接入 OCR，识别小红书/抖音/携程截图中的地点。
- 接入搜索能力，补充营业时间、价格、预约规则。
- 支持多人出行偏好协调。
- 扩展为旅行中实时陪伴 Agent。

## 项目说明

本项目重点展示从用户痛点、MVP 范围、Agent 工作流、交互原型到后端接口设计的完整产品思考。


