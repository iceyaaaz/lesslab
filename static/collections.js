// 收藏与归档独立于 AI 计划；这些操作不会调用模型。
(() => {
    const byId = id => document.getElementById(id);
    const form = byId("resource-form");
    const saveButton = byId("save-button");
    const formMessage = byId("form-message");
    const filter = byId("status-filter");
    const search = byId("search-input");
    const inFlight = new Set();
    const versions = {active: 0, archive: 0};

    async function request(url, options = {}) {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 15000);
        try {
            const response = await fetch(url, {...options, signal: controller.signal});
            const data = await response.json().catch(() => null);
            if (!response.ok) throw new Error(typeof data?.detail === "string" ? data.detail : "请求失败，请检查填写内容或数据库连接。");
            if (!data) throw new Error("服务器返回格式异常。");
            return data;
        } finally { clearTimeout(timer); }
    }

    function errorText(error) {
        return error.name === "AbortError" || error instanceof TypeError
            ? "连接中断或超时，请刷新列表确认结果后再重试。" : error.message;
    }

    async function changeResource(resource, archived, action, button) {
        if (inFlight.has(resource.id)) return;
        inFlight.add(resource.id);
        const oldText = button.textContent;
        button.disabled = true;
        button.textContent = "更新中……";
        byId("collection-operation").textContent = "";
        byId("archive-operation").textContent = "";
        const message = byId(archived ? "archive-operation" : "collection-operation");
        message.textContent = "正在更新……";
        const isArchiveAction = action === "archive";
        try {
            await request(`/resources/${resource.id}/${isArchiveAction ? "archive" : "status"}`, {
                method: "PATCH", headers: {"Content-Type": "application/json"},
                body: JSON.stringify(isArchiveAction ? {archived: !archived} : {status: resource.status === "done" ? "unread" : "done"}),
            });
            const results = await Promise.all([loadResources(false), loadResources(true)]);
            message.textContent = isArchiveAction
                ? archived ? "已恢复到资料收件箱，原来的学习状态已保留。" : "已归档，可在左侧“归档资料”中恢复。新的学习计划会跳过它。"
                : "学习状态已更新；已有计划如需调整，请重新生成。";
            if (results.includes(false)) message.textContent += " 部分列表刷新失败，请点击刷新重试。";
        } catch (error) { message.textContent = errorText(error); }
        finally {
            inFlight.delete(resource.id);
            button.disabled = false;
            button.textContent = oldText;
        }
    }

    function renderCard(resource, archived) {
        const card = document.createElement("article");
        card.className = "card collection-card";
        const title = document.createElement("h3");
        title.textContent = resource.title;
        const status = document.createElement("p");
        status.textContent = `${archived ? "已归档 · 原状态" : "状态"}：${resource.status === "done" ? "已完成 ✓" : "待学习"}`;
        const duration = document.createElement("p");
        duration.textContent = resource.estimated_minutes == null ? "预计时长：未填写" : `预计时长：${resource.estimated_minutes} 分钟`;
        card.append(title, status, duration);
        try {
            const url = new URL(resource.url);
            if (["https:", "http:"].includes(url.protocol)) {
                const link = document.createElement("a");
                Object.assign(link, {href: url.href, target: "_blank", rel: "noopener noreferrer", textContent: "打开原文 ↗", className: "original-link"});
                card.append(link);
            }
        } catch { /* 无效链接不影响资料整理。 */ }
        const actions = document.createElement("div");
        actions.className = "resource-actions";
        function addButton(text, action) {
            const button = document.createElement("button");
            button.type = "button";
            button.textContent = text;
            button.addEventListener("click", () => changeResource(resource, archived, action, button));
            actions.append(button);
        }
        if (!archived) addButton(resource.status === "done" ? "改回待学习" : "标记已完成", "status");
        addButton(archived ? "恢复到收件箱" : "归档", "archive");
        card.append(actions);
        return card;
    }

    async function loadResources(archived = false) {
        const key = archived ? "archive" : "active";
        const version = ++versions[key];
        const message = byId(archived ? "archive-message" : "list-message");
        const list = byId(archived ? "archive-list" : "resource-list");
        message.textContent = "正在读取资料……";
        try {
            const data = await request(`/resources?archived=${archived}`);
            if (version !== versions[key]) return true;
            if (!Array.isArray(data.items)) throw new Error("资料列表格式异常。");
            const keyword = search.value.trim().toLowerCase();
            const items = archived ? data.items : data.items.filter(item =>
                (filter.value === "all" || item.status === filter.value) && item.title.toLowerCase().includes(keyword));
            const cards = document.createDocumentFragment();
            for (const item of items) cards.append(renderCard(item, archived));
            list.replaceChildren(cards);
            if (archived) {
                message.textContent = data.items.length ? `最近加载 ${data.items.length} 条归档资料（最多 100 条）。可随时恢复，归档不会删除内容。` : "还没有归档资料。暂时不学的内容，可以先收在这里。";
            } else {
                const unread = data.items.filter(item => item.status === "unread").length;
                message.textContent = `最近加载 ${data.items.length} 条未归档收藏（最多 100 条）：待学习 ${unread} 条，已完成 ${data.items.length - unread} 条。当前筛选显示 ${items.length} 条。`;
                if (!items.length) message.textContent += " 当前范围暂无收藏。";
            }
            return true;
        } catch (error) {
            if (version === versions[key]) message.textContent = `${errorText(error)} 列表未更新，请点击刷新重试。`;
            return false;
        }
    }

    byId("search-form").addEventListener("submit", event => {event.preventDefault(); void loadResources();});
    filter.addEventListener("change", () => loadResources());
    byId("collection-refresh").addEventListener("click", () => loadResources());
    byId("archive-refresh").addEventListener("click", () => loadResources(true));
    form.addEventListener("submit", async event => {
        event.preventDefault();
        if (saveButton.disabled) return;
        const title = byId("title").value.trim();
        const url = byId("url").value.trim();
        const rawMinutes = byId("estimated-minutes").value;
        const estimated_minutes = rawMinutes === "" ? null : Number(rawMinutes);
        if (!title || (estimated_minutes !== null && (!Number.isInteger(estimated_minutes) || estimated_minutes < 1 || estimated_minutes > 600))) {
            formMessage.textContent = "请填写标题；时长须为 1—600 的整数或留空。";
            return;
        }
        saveButton.disabled = true;
        saveButton.textContent = "保存中……";
        try {
            await request("/resources", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({title, url, estimated_minutes})});
            form.reset();
            formMessage.textContent = "收藏已保存！";
            if (!await loadResources()) formMessage.textContent += " 列表刷新失败，请点击刷新。";
        } catch (error) { formMessage.textContent = `${errorText(error)} 如结果不确定，请先刷新列表确认，避免重复添加。`; }
        finally { saveButton.disabled = false; saveButton.textContent = "保存收藏"; }
    });
    void loadResources();
    void loadResources(true);
})();
