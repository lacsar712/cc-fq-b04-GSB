# FASTQ 质控流水线台（FASTQ QC Pipeline Console）

从零实现的全栈演示：上传/选择小型 FASTQ → **Actor 队列流水线**质控 → 查看阶段状态与指标。

## 技术栈

| 层 | 技术 |
|----|------|
| 后端 | Python 3.11 · FastAPI · SQLAlchemy · PostgreSQL |
| 流水线 | `ParseActor` → `QualityHistActor` → `NContentActor` → `ReportActor`（asyncio.Queue） |
| 前端 | Vue 3 · Vite · Quasar · 中文 UI · nginx `/api` 反代 |
| 基建 | docker compose（db / backend / seed / frontend） |

## 端口

| 服务 | 地址 |
|------|------|
| Frontend | http://localhost:3184 |
| Backend API | http://localhost:8184 |
| PostgreSQL | localhost:54384 |

> 对外端口号为固定约定，迭代不改号（3184 / 8184 / 54384）。

## 账号

| 用户 | 密码 | 权限 |
|------|------|------|
| `bioops` | `fastq123456` | 可提交质控作业 |
| `auditor` | `audit123456` | 只读结果，不可开跑（提交接口返回 403，前端无提交入口且按钮禁用） |

## 同日重复开跑策略（写死）

同一自然日（**UTC 日期**）内，同一来源只允许开跑一次，**第二次直接拒绝**（不是警告）：

- **样例库提交**：按 `sample_id` 判重。
- **纯文本自定义输入**：按规范化文本的 SHA-256 判重（规则见下节）。
- 无论上一次作业成功 / 失败 / 排队中，都计入判重；两个来源池互相独立。
- 策略写死在 `backend/app/policy.py`，不接受请求参数覆盖。

**接口与页面同一套说法**：拒绝时接口返回 `409 Conflict`，
`detail = { "code": "duplicate_same_day", "message": "...", "existingJobId": N }`；
提交页原样展示该 `message` 横幅，并提供「查看已有作业 #N」跳转。

**可追溯**：每一次开跑尝试（`created` / `rejected_duplicate` / `rejected_forbidden`）
都写入 `job_attempts` 审计表，任何登录用户（含审计员）可通过
`GET /api/attempts` 或「作业历史」页的「开跑尝试记录」表查看。

## 纯文本自定义输入规则

`POST /api/jobs` 传 `{ "fastqText": "..." }` 时适用，与样例库提交相互独立：

1. 若同时传了 `sampleId` 与 `fastqText`，**优先使用样例**，文本被忽略。
2. 文本先做规范化：`\r\n` / `\r` 统一为 `\n`，去掉首尾空白。
3. 规范化后为空 → `400`；超过 **200000 字符** → `400`。
4. 判重指纹 = 规范化文本的 SHA-256（存入 `jobs.content_hash`，历史页可见前 12 位）；
   同日同指纹的自定义文本作业已存在 → `409` 拒绝。与样例库按 `sample_id`
   判重的池子互不影响。
5. FASTQ 结构（四行一组、长度一致、合法碱基）不在提交时校验，
   由流水线的 `ParseActor` 在开跑后判定，失败体现在作业阶段状态中。

## 一键启动

```bash
cd projects/09-fastq-qc-pipeline
docker compose up --build
```

镜像源：Postgres/Node/Nginx 使用 `docker.m.daocloud.io`；npm 使用 `registry.npmmirror.com`；pip 使用清华源。

启动后 seed 会写入：

- `demo-good-r1`：合格样例（可算出 `mean_quality` / `n_rate`）
- `demo-broken-malformed`：损坏样例（`ParseActor` 失败，后续阶段 skipped）

## Verification（验收）

1. 打开 http://localhost:3184 ，用 `bioops` / `fastq123456` 登录。
2. **样例库** 看到 2 条样例 → 选合格样例 **提交质控作业**。
3. 作业详情页看到四个 Actor 阶段均为成功，指标卡出现 `reads` / `mean_quality` / `n_rate`。
4. **同日重复开跑自测**：对同一合格样例再次提交 → 接口返回 409，提交页出现与接口同文案的
   拒绝横幅（可跳转已有作业）；「作业历史」页的「开跑尝试记录」新增一条 `同日重复被拒`。
5. 再跑损坏样例：`ParseActor` = failed，其余 = skipped。
6. 退出，用 `auditor` / `audit123456` 登录：可看历史、详情与尝试记录；提交作业接口返回 403，
   前端无提交入口、提交按钮禁用；越权尝试同样留痕（`越权被拒`）。
7. 健康检查：`curl http://localhost:8184/api/health`

## API

- `POST /api/auth/login`
- `GET  /api/health`
- `GET  /api/samples`
- `POST /api/jobs` `{ "sampleId": 1 }` 或 `{ "fastqText": "..." }`
  - `201` 创建成功；`400` 输入为空/超长；`403` 审计员越权（留痕）；
    `409` 同日重复开跑被拒（留痕，`detail.existingJobId` 指向已有作业）
- `GET  /api/jobs`
- `GET  /api/jobs/{id}`
- `GET  /api/jobs/{id}/stages`
- `GET  /api/attempts` 开跑尝试审计（含被拒的重复/越权尝试）

## 本地单测（可选）

```bash
cd backend
pip install -r requirements.txt
pytest -q
```

覆盖：畸形 FASTQ 在 `ParseActor` 失败；正常样例产出 `mean_quality`；
同日二次开跑被拒（样例与自定义文本两条路径）、审计员 403 留痕、尝试记录可追溯。

## 目录结构

```
09-fastq-qc-pipeline/
  PRD.md
  README.md
  docker-compose.yml
  backend/
    Dockerfile
    seed.py
    data/{good,broken}.fastq
    app/
      main.py api.py auth.py models.py schemas.py policy.py
      pipeline/{actors,runner}.py
    tests/{test_actors,test_duplicate_policy}.py
  frontend/
    Dockerfile nginx.conf
    src/pages/{Login,Samples,JobSubmit,JobDetail,JobHistory}Page.vue
```
