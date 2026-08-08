# 安全修复 diff — 1 中风险 + 4 低风险

> 审核人：林深-安全合规员
> 日期：2026-08-08
> 对象：行者-Linux专家 负责的 5 个文件
> 用途：一次性改完，避免反复修

---

## 修复 1【中风险】verify_seed() 定义但 main() 未调用

**文件**：`modelscope/entrypoint.sh`
**问题**：`verify_seed()` 函数在 line 90-107 已定义，但 `main()`（line 237-254）从未调用它。§6.2 种子配置完整性校验形同虚设——若种子配置被篡改，容器启动时无法发现。
**修复**：在 `main()` 的 `init_persistence` 之后、`generate_htpasswd` 之前加入种子校验调用。若当前尚无种子配置文件，用条件判断跳过（避免阻塞首次启动）。

```diff
--- entrypoint.sh (line 237-254)
+++ entrypoint.sh (修复后)
 main() {
     log "=== Zephyr AI Desktop Entry Point ==="
 
     # Step 0: 持久化初始化
     init_persistence
 
+    # Step 0.5: 种子配置完整性校验 (§6.2)
+    # 若镜像内置了种子配置的 sha256 清单，则逐项校验
+    local seed_manifest="/opt/zephyr/seeds/SHA256SUMS"
+    if [ -f "$seed_manifest" ]; then
+        log "Verifying seed configs..."
+        while IFS= read -r line; do
+            # 行格式: <sha256>  <filename>
+            local expected_hash file
+            expected_hash=$(echo "$line" | awk '{print $1}')
+            file=$(echo "$line" | awk '{print $2}')
+            verify_seed "/opt/zephyr/seeds/${file}" "$expected_hash"
+        done < "$seed_manifest"
+    else
+        warn "No seed manifest found at ${seed_manifest}, skipping seed verification"
+    fi
+
     # Step 1: 生成安全配置
     generate_htpasswd
     generate_vnc_password
     generate_rclone_config
 
     # Step 2: 最终权限校验
     final_permission_check
 
     # Step 3: 启动 supervisord（前台运行，作为 PID 1）
     log "Starting supervisord..."
     exec /usr/bin/supervisord -n -c /etc/supervisor/conf.d/supervisord.conf
 }
```

> **说明**：种子清单文件 `/opt/zephyr/seeds/SHA256SUMS` 由 Dockerfile 构建时生成（海豚负责）。格式与 `sha256sum` 标准输出一致。若海豚尚未生成该文件，`warn` 跳过不阻塞启动。

---

## 修复 2【低风险】generate_rclone_config() 缺少 RCLONE_CRYPT_PASSWORD 前置校验

**文件**：`modelscope/entrypoint.sh`
**问题**：当前逻辑只在 `ONEDRIVE_TOKEN` 缺失时跳过，但若 `ONEDRIVE_TOKEN` 存在而 `RCLONE_CRYPT_PASSWORD` / `RCLONE_CRYPT_PASSWORD2` 缺失，会生成含空密码字段的 rclone.conf。虽然后续 `rclone listremotes` 会失败并 `fail()`，但 fail-fast 更好——应在开头校验所有必需 Secret。

```diff
--- entrypoint.sh (line 179-189)
+++ entrypoint.sh (修复后)
 generate_rclone_config() {
     log "Generating rclone.conf at runtime"
 
     local rclone_conf="${PERSIST_ROOT}/config/rclone.conf"
     mkdir -p "$(dirname "$rclone_conf")"
 
-    # 仅在所有必需的 Secret 都存在时生成
+    # 分级校验：ONEDRIVE_TOKEN 缺失 = 用户不需要备份，跳过
     if [ -z "${ONEDRIVE_TOKEN:-}" ]; then
         warn "ONEDRIVE_TOKEN not set, skipping rclone config generation"
         return 0
     fi
 
+    # ONEDRIVE_TOKEN 存在 = 用户要备份，其余 Secret 必须齐全
+    if [ -z "${RCLONE_CRYPT_PASSWORD:-}" ] || [ -z "${RCLONE_CRYPT_PASSWORD2:-}" ]; then
+        fail "ONEDRIVE_TOKEN set but RCLONE_CRYPT_PASSWORD/RCLONE_CRYPT_PASSWORD2 missing — cannot generate valid crypt config"
+    fi
+
     cat > "$rclone_conf" <<EOF
 [onedrive]
 type = onedrive
```

---

## 修复 3【低风险】portal.conf /health 的 add_header 在 return 后不生效

**文件**：`modelscope/nginx/portal.conf`
**问题**：nginx 的 `return` 指令会立即终止请求处理并返回响应，写在 `return` 之后的 `add_header` 不会执行。当前 `/health` 端点返回的响应没有 `Content-Type` 头，浏览器可能误判为 `application/octet-stream` 触发下载。

```diff
--- portal.conf (line 131-135)
+++ portal.conf (修复后)
     location = /health {
         access_log off;
-        return 200 "ok\n";
         add_header Content-Type text/plain;
+        return 200 "ok\n";
     }
```

> **说明**：`add_header` 必须在 `return` 之前，nginx 才会在响应头中附加该头。

---

## 修复 4【低风险】keepalive.yml status 检查无错误处理

**文件**：`.github/workflows/keepalive.yml`
**问题**：若 curl 失败（网络超时）或 jq 解析失败（API 返回非 JSON / 502），`STATE` 为空或 `"null"`。此时 `if: steps.status.outputs.state == 'Stopped'` 判定为 false，静默跳过 deploy。这是 fail-safe 的（不会误重建），但会静默吞掉错误——空间实际已宕机却无告警。

```diff
--- keepalive.yml (line 20-28)
+++ keepalive.yml (修复后)
       - name: Check space status
         id: status
+        env:
+          MODELSCOPE_API_URL: ${{ secrets.MODELSCOPE_API_URL }}
+          SPACE_ID: ${{ secrets.SPACE_ID }}
+          MODELSCOPE_TOKEN: ${{ secrets.MODELSCOPE_TOKEN }}
         run: |
-          STATE=$(curl -s -X GET \
-            "${{ secrets.MODELSCOPE_API_URL }}/api/v1/spaces/${{ secrets.SPACE_ID }}/status" \
-            -H "Authorization: Bearer ${{ secrets.MODELSCOPE_TOKEN }}" | \
-            jq -r '.data.status')
+          RESPONSE=$(curl -s -f -X GET \
+            "${MODELSCOPE_API_URL}/api/v1/spaces/${SPACE_ID}/status" \
+            -H "Authorization: Bearer ${MODELSCOPE_TOKEN}") || {
+            echo "::error::Failed to fetch space status (curl error)"
+            echo "state=Error" >> $GITHUB_OUTPUT
+            exit 1
+          }
+          STATE=$(echo "$RESPONSE" | jq -r '.data.status // empty')
+          if [ -z "$STATE" ]; then
+            echo "::error::Space status API returned empty/null state"
+            echo "::error::Response: $RESPONSE"
+            echo "state=Error" >> $GITHUB_OUTPUT
+            exit 1
+          fi
           echo "state=$STATE" >> $GITHUB_OUTPUT
           echo "Space status: $STATE"
```

> **说明**：
> - `curl -f` 在 HTTP 错误码时返回非零退出码，触发 `|| { ... }` 错误分支
> - `jq -r '.data.status // empty'` 用 `// empty` 处理 null/缺失字段
> - `exit 1` 使 job 失败，触发下方 `Alert on failure` step

---

## 修复 5【低风险】keepalive.yml deploy step 的 Secret 直接嵌入 + 同上 env 传递

**文件**：`.github/workflows/keepalive.yml`
**问题**：`deploy` step 和 `Alert` step 同样直接用 `${{ secrets.* }}` 嵌入 shell 命令。GitHub Actions secrets 虽不会在日志中显示，但推荐用 `env:` 传递——避免 Shell 展开顺序导致的意外行为，也符合 GitHub 官方安全编码规范。

```diff
--- keepalive.yml (line 30-52)
+++ keepalive.yml (修复后)
       - name: Deploy only if stopped
         if: steps.status.outputs.state == 'Stopped'
+        env:
+          MODELSCOPE_API_URL: ${{ secrets.MODELSCOPE_API_URL }}
+          SPACE_ID: ${{ secrets.SPACE_ID }}
+          MODELSCOPE_TOKEN: ${{ secrets.MODELSCOPE_TOKEN }}
         run: |
           for i in 1 2 3; do
             HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
-              "${{ secrets.MODELSCOPE_API_URL }}/api/v1/spaces/${{ secrets.SPACE_ID }}/deploy" \
-              -H "Authorization: Bearer ${{ secrets.MODELSCOPE_TOKEN }}")
+              "${MODELSCOPE_API_URL}/api/v1/spaces/${SPACE_ID}/deploy" \
+              -H "Authorization: Bearer ${MODELSCOPE_TOKEN}")
             if [ "$HTTP_CODE" = "200" ]; then
               echo "Deploy succeeded on attempt $i"
               exit 0
             fi
             echo "Attempt $i failed (HTTP $HTTP_CODE), retrying in 10s..."
             sleep 10
           done
           echo "::error::Deploy failed after 3 attempts"
           exit 1
 
       - name: Alert on failure
         if: failure()
+        env:
+          ALERT_WEBHOOK: ${{ secrets.ALERT_WEBHOOK }}
+          SPACE_ID: ${{ secrets.SPACE_ID }}
         run: |
-          # 接 Telegram / 飞书 / 邮件 webhook
-          curl -s -X POST "${{ secrets.ALERT_WEBHOOK }}" \
-            -d "Keepalive deploy failed for space ${{ secrets.SPACE_ID }}"
+          if [ -z "$ALERT_WEBHOOK" ]; then
+            echo "::warning::ALERT_WEBHOOK not configured, skipping alert"
+            exit 0
+          fi
+          curl -s -X POST "${ALERT_WEBHOOK}" \
+            -d "Keepalive deploy failed for space ${SPACE_ID}"
```

> **说明**：Alert step 额外加了 `ALERT_WEBHOOK` 空值保护——用户可能暂未配置告警 webhook，不应因告警 step 自身失败而导致 job 状态混乱。

---

## 修复优先级总结

| # | 级别 | 文件 | 一句话 |
|---|---|---|---|
| 1 | 中 | entrypoint.sh | main() 加 verify_seed 调用 |
| 2 | 低 | entrypoint.sh | generate_rclone_config 加 RCLONE_CRYPT_PASSWORD 校验 |
| 3 | 低 | portal.conf | /health 的 add_header 移到 return 前 |
| 4 | 低 | keepalive.yml | status 检查加 curl -f + jq null 处理 + ::error:: |
| 5 | 低 | keepalive.yml | 全部 secrets 改用 env: 传递 |

5 处改动均为局部 diff，不影响现有逻辑。改完后我再审一遍完整文件。

— 林深-安全合规员
