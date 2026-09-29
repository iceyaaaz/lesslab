(() => {
    const $ = id => document.getElementById(id);
    const form = $("current-goal-form");
    const fields = [$("goal-title-input"), $("goal-criteria-input"), $("goal-date-input"), $("goal-minutes-input")];
    const saveButton = $("goal-save-button");
    const reloadButton = $("goal-reload-button");
    const message = $("goal-message");
    const applyButtons = [$("goal-plan-button"), $("apply-current-goal")];
    const aiGoal = $("ai-goal");
    const aiMinutes = $("ai-minutes");
    let savedGoal = null;
    let version = null;
    let busy = false;
    let aiEdited = false;

    function markEdited() {
        aiEdited = true;
        $("current-goal-plan-note").textContent = "当前为临时计划输入，不会修改首页已保存的目标。点击“带入当前目标”可以重新填入。";
    }
    aiGoal.addEventListener("input", markEdited);
    aiMinutes.addEventListener("input", markEdited);

    function setBusy(value) {
        busy = value;
        fields.forEach(field => { field.disabled = value || version === null; });
        saveButton.disabled = value || version === null;
        reloadButton.disabled = value;
        applyButtons.forEach(button => { button.disabled = value || !savedGoal; });
    }

    async function request(options = {}) {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 15000);
        try {
            const response = await fetch("/current-goal", {...options, signal: controller.signal});
            const data = await response.json().catch(() => null);
            if (!response.ok) throw new Error(typeof data?.detail === "string" ? data.detail : "请检查目标内容、日期和时长。");
            if (!data || !Number.isInteger(data.version) || !(data.goal === null || typeof data.goal?.title === "string")) throw new Error("目标数据格式异常，请重新读取。");
            return data;
        } finally { clearTimeout(timer); }
    }

    function errorText(error) {
        return error.name === "AbortError" || error instanceof TypeError
            ? "连接中断或超时。请先重新读取已保存目标，确认结果后再修改。" : error.message;
    }

    function render(data) {
        savedGoal = data.goal;
        version = data.version;
        $("current-goal-title").textContent = savedGoal?.title || "设置一个你想完成的目标";
        $("current-goal-meta").textContent = savedGoal
            ? `默认每次 ${savedGoal.daily_minutes} 分钟 · ${savedGoal.due_date ? "目标日期 " + savedGoal.due_date : "未设置目标日期"}`
            : "保存后，这里会显示你的目标和默认安排。";
        $("current-goal-criteria").textContent = savedGoal?.success_criteria ? `验收标准：${savedGoal.success_criteria}` : "";
        fields[0].value = savedGoal?.title || "";
        fields[1].value = savedGoal?.success_criteria || "";
        fields[2].value = savedGoal?.due_date || "";
        fields[3].value = savedGoal?.daily_minutes ?? 30;
    }

    function fillPlan(manual = false) {
        if (!savedGoal) return false;
        if (aiGoal.disabled || aiMinutes.disabled || $("ai-plan-button").disabled) {
            if (manual) $("current-goal-plan-note").textContent = "计划正在处理，请完成后再带入目标。";
            return false;
        }
        if (!manual && (aiEdited || aiGoal.value.trim())) return false;
        aiGoal.value = savedGoal.title + (savedGoal.success_criteria ? `\n验收标准：${savedGoal.success_criteria}` : "");
        aiMinutes.value = savedGoal.daily_minutes;
        $("current-goal-plan-note").textContent = "已带入保存的目标和默认时长，可以临时修改。已有计划不会自动改变，点击生成后才会调用 AI。";
        return true;
    }

    async function load() {
        if (busy) return;
        setBusy(true);
        message.textContent = "正在读取目标……";
        try {
            render(await request());
            fillPlan();
            message.textContent = savedGoal ? "已读取保存的目标。修改当前目标不会改写历史计划。" : "先设置一个当前目标；后续可以随时调整。";
        } catch (error) {
            message.textContent = errorText(error);
            if (version === null) {
                $("current-goal-title").textContent = "暂时无法读取目标";
                $("current-goal-meta").textContent = "请展开下方表单，点击重新读取已保存目标。";
            }
        }
        finally { setBusy(false); }
    }

    form.addEventListener("submit", async event => {
        event.preventDefault();
        if (busy || version === null) return;
        const title = fields[0].value.trim();
        const success_criteria = fields[1].value.trim();
        const daily_minutes = Number(fields[3].value);
        if (title.length < 2 || title.length > 200 || success_criteria.length > 250 || !Number.isInteger(daily_minutes) || daily_minutes < 1 || daily_minutes > 600) {
            message.textContent = "目标填写 2—200 个字符，验收标准最多 250 个字符，时长为 1—600 的整数。";
            return;
        }
        const payload = {title, success_criteria, due_date: fields[2].value || null, daily_minutes, version};
        setBusy(true);
        saveButton.textContent = "正在保存……";
        try {
            render(await request({method: "PUT", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)}));
            const applied = fillPlan();
            if (!applied) $("current-goal-plan-note").textContent = "首页目标已更新，当前计划输入保持不变。点击“带入当前目标”可使用最新保存的设置。";
            message.textContent = applied ? "目标已保存，并已带入行动计划。" : "目标已保存。可点击“用此目标安排计划”带入最新内容。";
            $("goal-editor").open = false;
        } catch (error) { message.textContent = errorText(error); }
        finally { saveButton.textContent = "保存目标"; setBusy(false); }
    });

    reloadButton.addEventListener("click", load);
    $("goal-edit-button").addEventListener("click", () => {
        $("goal-editor").open = true;
        fields[0].focus();
    });
    applyButtons.forEach(button => button.addEventListener("click", () => {
        location.hash = "plans";
        fillPlan(true);
    }));
    void load();
})();
