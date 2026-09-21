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

## 账号

| 用户 | 密码 | 权限 |
|------|------|------|
| `bioops` | `fastq123456` | 可提交质控作业 |
| `auditor` | `audit123456` | 只读结果与留痕，不可提交（接口固定返回 403） |

## 同日同样例开跑策略（写死）

- **策略：拒绝第二次。** 同一 `sampleId` 在同一 UTC 自然日内已存在作业（任意状态、任意提交人）时，`POST /api/jobs` 返回 **409**，不创建新作业。
- **接口与页面同一套说法**：拒绝文案由后端 `app/policy.py` 统一生成，页面横幅原样展示接口 `detail`，不另行改写。文案形如：
  > 拒绝重复开跑：样例「demo-good-r1」今日（2026-09-21，UTC）已开跑过（作业 #3，提交人 bioops）。写死策略：同一样例同日仅允许开跑一次，本次已拒绝并留痕。
- **可追溯**：每次被拒绝的重复尝试写入 `audit_events` 表（尝试人、样例、当日已开跑作业 ID、完整文案、时间），可通过 `GET /api/audit-events` 查询（审计员可读），页面「作业历史 → 重复开跑留痕（审计）」同步展示。
- **跨天不拦截**：次日（UTC 0 点过后）可再次开跑同一样例。
- 自定义纯文本输入没有样例身份，**不参与**该去重，规则见下节。

## 自定义输入（纯文本）规则

提交 `POST /api/jobs` 时不传 `sampleId`、改传 `fastqText` 即为自定义输入，规则单独写清（写死于 `app/policy.py` 的 `validate_custom_fastq`）：

1. 与 `sampleId` 二选一；两者都给时**以样例为准**，忽略文本。
2. 去首尾空白后不能为空，否则 400「请提供 sampleId 或 fastqText」。
3. 长度不超过 **100000 字符**，否则 400。
4. 首行须以 `@` 开头（FASTQ 表头），否则 400。
5. 更深的格式校验（四行一组、序列与质量串等长、合法碱基）由 `ParseActor` 在流水线内完成；不合规时**作业失败**，而不是提交被拒。
6. 自定义输入不参与「同日同样例」去重，每次提交都新建作业。

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
4. 再跑损坏样例：`ParseActor` = failed，其余 = skipped。
5. **同日同样例再次开跑（自测）**：当天再对 `demo-good-r1` 提交一次 → 接口返回 409，提交页红色横幅展示与接口一致的拒绝文案；**作业历史** 页「重复开跑留痕（审计）」新增一条记录。
6. 退出，用 `auditor` / `audit123456` 登录：可看历史、详情与留痕，提交作业接口返回 403 / 前端无提交入口。
7. 健康检查：`curl http://localhost:8184/api/health`

## API

- `POST /api/auth/login`
- `GET  /api/health`
- `GET  /api/samples`
- `POST /api/jobs` `{ "sampleId": 1 }` 或 `{ "fastqText": "..." }`（同日同样例重复 → 409）
- `GET  /api/jobs`
- `GET  /api/jobs/{id}`
- `GET  /api/jobs/{id}/stages`
- `GET  /api/audit-events`（重复开跑留痕）

## 本地单测（可选）

```bash
cd backend
pip install -r requirements.txt
pytest -q
```

覆盖：畸形 FASTQ 在 `ParseActor` 失败；正常样例产出 `mean_quality`；同日同样例重复开跑返回 409 并留痕；审计员提交返回 403；自定义纯文本输入规则。

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
