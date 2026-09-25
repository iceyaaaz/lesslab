// 单独作用域，避免与原来的收藏、规则计划脚本重名。
(() => {
    const form = document.getElementById("ai-plan-form");
    const goalInput = document.getElementById("ai-goal");
    const minutesInput = document.getElementById("ai-minutes");
    const button = document.getElementById("ai-plan-button");
    const message = document.getElementById("ai-plan-message");
    const usageMessage = document.getElementById("ai-plan-usage");
    const list = document.getElementById("ai-plan-list");

    if (!form || !goalInput || !minutesInput || !button || !message || !usageMessage || !list) {
        console.error("AI 计划区域缺少必要元素，请检查 HTML 中的 id。");
        return;
    }

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (button.disabled) return;

        const goal = goalInput.value.trim();
        const minutes = Number(minutesInput.value);
        if (goal.length < 2 || goal.length > 500) {
            message.textContent = "请填写 2—500 个字符的学习目标。";
            return;
        }
        if (!Number.isInteger(minutes) || minutes < 1 || minutes > 600) {
            message.textContent = "可用时间须为 1—600 的整数。";
            return;
        }

        button.disabled = true;
        goalInput.disabled = true;
        minutesInput.disabled = true;
        button.textContent = "AI 正在安排……";
        message.textContent = "正在生成计划，请稍候。";
        usageMessage.textContent = "";
        list.replaceChildren();

        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 60000);

        try {
            // 只请求自己的后端，API Key 不进入浏览器。
            const response = await fetch("/ai-study-plan", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ goal, minutes }),
                signal: controller.signal,
            });
            const data = await response.json().catch(() => null);

            if (!response.ok) {
                const detail = typeof data?.detail === "string"
                    ? data.detail
                    : "生成失败，请检查填写内容或稍后重试。";
                throw new Error(detail);
            }
            if (!data || !Array.isArray(data.items) || !["ai", "no_candidates"].includes(data.mode)) {
                throw new Error("没有收到可用的计划，请稍后重试。");
            }

            // 模型文字以纯文本显示，不作为 HTML 执行。
            const cards = document.createDocumentFragment();
            for (const [index, resource] of data.items.entries()) {
                const card = document.createElement("article");
                card.className = "card";

                const title = document.createElement("h3");
                title.textContent = `${index + 1}. ${resource.title}`;

                const duration = document.createElement("p");
                duration.textContent = `预计学习 ${resource.estimated_minutes} 分钟`;

                const reason = document.createElement("p");
                reason.style.marginTop = "12px";
                reason.textContent = `推荐理由：${resource.reason}`;

                card.append(title, duration, reason);

                try {
                    const url = new URL(resource.url);
                    if (["http:", "https:"].includes(url.protocol)) {
                        const link = document.createElement("a");
                        link.href = url.href;
                        link.textContent = "开始学习 ↗";
                        link.target = "_blank";
                        link.rel = "noopener noreferrer";
                        link.className = "original-link";
                        card.append(link);
                    }
                } catch {
                    // 链接无效时仍然显示建议。
                }

                cards.append(card);
            }
            list.append(cards);

            message.textContent = data.items.length > 0
                ? `AI 从 ${data.candidate_count} 条候选中安排了 ${data.items.length} 项内容，` +
                  `预计 ${data.total_minutes} 分钟，剩余 ${data.remaining_minutes} 分钟。`
                : data.message;

            if (data.mode === "no_candidates") {
                usageMessage.textContent = "本次未调用 AI，没有产生模型用量。";
            } else {
                const input = data.usage?.prompt_tokens ?? "未返回";
                const output = data.usage?.completion_tokens ?? "未返回";
                usageMessage.textContent = `本次用量：输入 ${input} token，输出 ${output} token。`;
            }
        } catch (error) {
            message.textContent = error.name === "AbortError"
                ? "等待超时，本次调用可能已产生用量，请稍后再决定是否重试。"
                : error instanceof TypeError
                    ? "网络连接中断，暂时无法确认生成结果，请稍后再试。"
                    : error.message;
            usageMessage.textContent = "生成失败不一定代表零费用，实际用量请以 DeepSeek 平台记录为准。";
        } finally {
            clearTimeout(timer);
            button.disabled = false;
            goalInput.disabled = false;
            minutesInput.disabled = false;
            button.textContent = "生成 AI 计划";
        }
    });
})();
