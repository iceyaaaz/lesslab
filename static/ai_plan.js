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

    const savePlanButton = document.getElementById("save-ai-plan-button");
    const savePlanMessage = document.getElementById("save-ai-plan-message");
    const historyRefresh = document.getElementById("history-refresh-button");
    const historyMore = document.getElementById("history-more-button");
    const historyMessage = document.getElementById("history-message");
    const historyList = document.getElementById("history-list");
    const detailMessage = document.getElementById("history-detail-message");
    const detailList = document.getElementById("history-detail");

    if (![savePlanButton, savePlanMessage, historyRefresh, historyMore,
          historyMessage, historyList, detailMessage, detailList].every(Boolean)) {
        console.error("历史计划区域缺少元素，请同时更新 index.html 和 ai_plan.js。");
        return;
    }

    let currentPlan = null;
    let historyOffset = 0;
    let historyRequest = 0;
    let detailRequest = 0;

    // 保存和读取只访问自己的数据库接口，不调用 AI。
    async function requestPlan(url, options = {}) {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 15000);
        try {
            const response = await fetch(url, { ...options, signal: controller.signal });
            const data = await response.json().catch(() => null);
            if (!response.ok) {
                const error = new Error(typeof data?.detail === "string"
                    ? data.detail : "请求失败，请检查服务或填写内容。");
                error.status = response.status;
                throw error;
            }
            if (!data) throw new Error("服务器返回的内容无法读取。");
            return data;
        } finally {
            clearTimeout(timer);
        }
    }

    function errorText(error) {
        if (error.name === "AbortError") return "请求超时，请检查服务是否正常运行。";
        if (error instanceof TypeError) return "连接中断，请检查服务是否正常运行。";
        return error.message;
    }

    function paragraph(text) {
        const p = document.createElement("p");
        p.textContent = text;
        p.style.marginTop = "12px";
        return p;
    }

    function sourceName(source) {
        return ({ ai: "AI 计划", rule: "规则计划", manual: "手动计划" })[source] || "学习计划";
    }

    function renderDetail(plan) {
        const card = document.createElement("article");
        card.className = "card";
        const heading = document.createElement("h3");
        heading.textContent = `计划 #${plan.id}：${plan.goal}`;
        const count = paragraph("正在读取完成进度……");
        count.setAttribute("role", "status");
        const progress = document.createElement("progress");
        progress.max = Math.max(1, plan.items.length);
        progress.value = 0;
        progress.hidden = true;
        progress.setAttribute("aria-label", "本计划完成进度");
        progress.className = "plan-progress-bar";
        const refresh = document.createElement("button");
        refresh.type = "button";
        refresh.className = "outline-button";
        refresh.textContent = "刷新进度";
        const status = paragraph("");
        status.setAttribute("role", "status");
        card.append(heading, paragraph(
            `${sourceName(plan.source)} · 预算 ${plan.budget_minutes} 分钟 · 预计 ${plan.total_minutes} 分钟`
        ), paragraph("勾选记录本计划的完成情况。收藏状态仍在资料收件箱中单独维护。"), count, progress, refresh, status);

        let busy = false;
        let loaded = false;
        const controls = new Map();
        function setBusy(value) {
            busy = value;
            refresh.disabled = value;
            for (const control of controls.values()) control.input.disabled = value || !loaded;
        }
        function applyProgress(data) {
            const valid = data?.plan_id === plan.id && Array.isArray(data.items)
                && data.items.length === controls.size
                && new Set(data.items.map(item => item.resource_id)).size === controls.size
                && data.items.every(item => controls.has(item.resource_id) && typeof item.completed === "boolean");
            if (!valid) throw new Error("完成进度格式异常，请刷新进度重试。");
            let completed = 0;
            for (const item of data.items) {
                const control = controls.get(item.resource_id);
                control.input.checked = item.completed;
                control.label.textContent = item.completed ? "已完成" : "标记完成";
                control.section.classList.toggle("task-completed", item.completed);
                if (item.completed) completed++;
            }
            loaded = true;
            progress.hidden = false;
            progress.value = completed;
            count.textContent = `已完成 ${completed} / ${controls.size} 项` + (controls.size > 0 && completed === controls.size ? "，这份计划已全部完成！" : "");
        }
        async function loadProgress() {
            if (busy) return;
            setBusy(true);
            status.textContent = "正在读取进度……";
            try {
                const data = await requestPlan(`/study-plans/${plan.id}/progress`);
                if (!card.isConnected) return;
                applyProgress(data);
                status.textContent = "已读取保存的进度。";
            } catch (error) {
                if (!card.isConnected) return;
                loaded = false;
                count.textContent = "进度暂不可用";
                progress.hidden = true;
                status.textContent = `${errorText(error)} 请点击“刷新进度”重试。`;
            } finally { setBusy(false); }
        }

        for (const [index, item] of plan.items.entries()) {
            const section = document.createElement("section");
            section.className = "plan-task";
            const title = document.createElement("h4");
            title.textContent = `${index + 1}. ${item.title}`;
            const label = document.createElement("label");
            label.className = "task-checkbox";
            const input = document.createElement("input");
            input.type = "checkbox";
            input.disabled = true;
            input.setAttribute("aria-label", `完成任务：${item.title}`);
            const labelText = document.createElement("span");
            labelText.textContent = "标记完成";
            label.append(input, labelText);
            controls.set(item.id, {input, label: labelText, section});
            section.append(title, paragraph(`预计学习 ${item.estimated_minutes} 分钟`));
            if (item.reason) section.append(paragraph(`推荐理由：${item.reason}`));
            try {
                const url = new URL(item.url);
                if (["http:", "https:"].includes(url.protocol)) {
                    const link = document.createElement("a");
                    Object.assign(link, {href: url.href, target: "_blank", rel: "noopener noreferrer", className: "original-link", textContent: "打开学习内容 ↗"});
                    section.append(link);
                }
            } catch { /* 快照中的无效链接仍可展示文字。 */ }
            section.append(label);
            card.append(section);
            input.addEventListener("change", async () => {
                const requested = input.checked;
                input.checked = !requested; // 以服务器保存结果为准。
                if (busy || !loaded) return;
                setBusy(true);
                status.textContent = "正在保存完成状态……";
                try {
                    const data = await requestPlan(`/study-plans/${plan.id}/tasks/${item.id}/completion`, {
                        method: "PUT", headers: {"Content-Type": "application/json"}, body: JSON.stringify({completed: requested}),
                    });
                    if (!card.isConnected) return;
                    applyProgress(data);
                    status.textContent = requested ? "已保存完成状态，刷新后仍会保留。" : "已改回未完成。";
                } catch (error) {
                    if (!card.isConnected) return;
                    loaded = false;
                    count.textContent = "请刷新进度确认最新状态";
                    progress.hidden = true;
                    status.textContent = `${errorText(error)} 暂时无法确认保存结果，请点击“刷新进度”，再决定是否重试。`;
                } finally { setBusy(false); }
            });
        }
        refresh.addEventListener("click", loadProgress);
        detailList.replaceChildren(card);
        void loadProgress();
    }

    async function showDetail(planId, detailButton) {
        const request = ++detailRequest;
        detailButton.disabled = true;
        detailMessage.textContent = `正在读取计划 #${planId}……`;
        detailList.replaceChildren();
        try {
            const plan = await requestPlan(`/study-plans/${planId}`);
            if (request !== detailRequest) return;
            if (!Array.isArray(plan.items)) throw new Error("计划详情格式异常。");
            renderDetail(plan);
            detailMessage.textContent = `正在查看计划 #${plan.id}。`;
        } catch (error) {
            if (request === detailRequest) detailMessage.textContent = errorText(error);
        } finally {
            detailButton.disabled = false;
        }
    }

    async function loadHistory(reset = false) {
        const request = ++historyRequest;
        const offset = reset ? 0 : historyOffset;
        historyRefresh.disabled = true;
        historyMore.disabled = true;
        historyMessage.textContent = "正在读取历史计划……";
        try {
            const data = await requestPlan(`/study-plans?limit=10&offset=${offset}`);
            if (request !== historyRequest) return;
            if (!Array.isArray(data.items)) throw new Error("历史计划格式异常。");
            const cards = document.createDocumentFragment();
            for (const plan of data.items) {
                const card = document.createElement("article");
                card.className = "card";
                const title = document.createElement("h3");
                title.textContent = `#${plan.id} ${plan.goal}`;
                const date = String(plan.created_at || "").replace("T", " ");
                const detailButton = document.createElement("button");
                detailButton.type = "button";
                detailButton.textContent = "查看详情";
                detailButton.style.marginTop = "16px";
                detailButton.addEventListener("click", () => showDetail(plan.id, detailButton));
                card.append(title, paragraph(
                    `${sourceName(plan.source)} · ${plan.item_count} 项 · 预计 ${plan.total_minutes}/${plan.budget_minutes} 分钟`
                ), paragraph(`保存时间：${date}`), detailButton);
                cards.append(card);
            }
            if (reset) historyList.replaceChildren();
            historyList.append(cards);
            historyOffset = offset + data.items.length;
            historyMore.hidden = !data.has_more;
            historyMessage.textContent = historyOffset
                ? `已加载 ${historyOffset} 份计划，最近保存的排在前面。`
                : "还没有历史计划，保存第一份后会显示在这里。";
        } catch (error) {
            if (request === historyRequest) {
                historyMessage.textContent = `${errorText(error)} 历史列表未更新，请点击“刷新历史”重试。`;
            }
        } finally {
            if (request === historyRequest) {
                historyRefresh.disabled = false;
                historyMore.disabled = false;
            }
        }
    }

    historyRefresh.addEventListener("click", () => loadHistory(true));
    historyMore.addEventListener("click", () => loadHistory(false));

    savePlanButton.addEventListener("click", async () => {
        if (!currentPlan || savePlanButton.disabled) return;
        // 保存期间禁止重复点击，以及生成另一份计划。
        savePlanButton.disabled = true;
        button.disabled = true;
        savePlanButton.textContent = "正在保存……";
        savePlanMessage.textContent = "正在保存到数据库……";
        try {
            const plan = await requestPlan("/study-plans", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(currentPlan),
            });
            if (!Number.isInteger(plan.id) || !Array.isArray(plan.items)) {
                throw new Error("保存响应格式异常。");
            }
            currentPlan = null;
            savePlanButton.textContent = "已保存";
            savePlanMessage.textContent = `已保存为计划 #${plan.id}，刷新网页后可在历史记录中查看。`;
            ++detailRequest;
            renderDetail(plan);
            detailMessage.textContent = `刚保存的计划 #${plan.id}（以保存时的数据为准）。`;
            void loadHistory(true);
        } catch (error) {
            if ([409, 422].includes(error.status)) {
                currentPlan = null;
                savePlanButton.textContent = "请重新生成计划";
                savePlanMessage.textContent = errorText(error);
            } else {
                savePlanButton.textContent = "重试保存";
                savePlanMessage.textContent = `${errorText(error)} 暂时无法确认是否已保存，请先刷新历史确认，避免重复保存。`;
                void loadHistory(true);
            }
        } finally {
            savePlanButton.disabled = currentPlan === null;
            button.disabled = false;
        }
    });

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

        currentPlan = null;
        savePlanButton.disabled = true;
        savePlanMessage.textContent = "生成完成后，请保存需要保留的计划。";
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

            // 保留本次生成时的目标和预算；修改输入框不会改变待保存的计划。
            if (data.mode === "ai" && data.items.length > 0) {
                currentPlan = {
                    goal,
                    budget_minutes: minutes,
                    source: "ai",
                    items: data.items.map(item => ({ id: item.id, reason: item.reason })),
                };
                savePlanButton.disabled = false;
                savePlanButton.textContent = "保存这份计划";
                savePlanMessage.textContent = `待保存目标：${goal}（预算 ${minutes} 分钟）。尚未保存，刷新会丢失。`;
            } else {
                savePlanMessage.textContent = "本次没有可保存的学习内容。";
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
            currentPlan = null;
            savePlanButton.disabled = true;
            savePlanMessage.textContent = "本次没有可保存的计划。";
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
    void loadHistory(true);
})();
