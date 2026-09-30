(() => {
    const $ = id => document.getElementById(id);
    const form = $("auth-form"), button = $("auth-submit"), toggle = $("auth-toggle");
    const password = $("password"), message = $("auth-message");
    let register = false;
    let registrationEnabled = false;
    async function request(url, options = {}) {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 15000);
        try {
            const response = await fetch(url, {...options, signal: controller.signal, credentials: "same-origin", cache: "no-store"});
            const data = await response.json().catch(() => null);
            if (!response.ok) throw new Error(typeof data?.detail === "string" ? data.detail : "请检查用户名与密码是否符合要求。");
            if (!data) throw new Error("账号服务返回异常，请重试。");
            return data;
        } finally { clearTimeout(timer); }
    }
    function setMode(value) {
        register = value;
        $("auth-heading").textContent = value ? "创建你的空间" : "回到你的空间";
        $("auth-description").textContent = value ? "从一个小目标开始，慢慢积累。" : "登录后，继续上次的计划。";
        button.textContent = value ? "创建账号" : "登录";
        toggle.textContent = value ? "已有账号，返回登录" : "创建一个新账号";
        password.autocomplete = value ? "new-password" : "current-password";
        password.minLength = value ? 15 : 1;
        password.value = "";
        $("password-hint").hidden = !value;
        message.textContent = "";
    }
    async function connect() {
        button.disabled = true;
        toggle.hidden = true;
        $("auth-retry").hidden = true;
        message.textContent = "正在连接账号服务……";
        try {
            const data = await request("/auth/status");
            if (data.setup_required) { message.textContent = "服务尚未初始化，请联系站点维护者。"; $("auth-retry").hidden = false; return; }
            registrationEnabled = data.registration_enabled === true;
            toggle.hidden = !registrationEnabled;
            button.disabled = false;
            message.textContent = registrationEnabled ? "" : "当前仅限已有账号登录。";
        } catch (error) {
            message.textContent = error.name === "AbortError" ? "连接超时，请重试。" : error.message;
            $("auth-retry").hidden = false;
        }
    }
    toggle.addEventListener("click", () => { if (registrationEnabled) setMode(!register); });
    $("auth-retry").addEventListener("click", connect);
    form.addEventListener("submit", async event => {
        event.preventDefault();
        if (button.disabled) return;
        button.disabled = true;
        toggle.disabled = true;
        message.textContent = register ? "正在创建账号……" : "正在登录……";
        try {
            await request(register ? "/auth/register" : "/auth/login", {
                method: "POST", headers: {"Content-Type": "application/json"},
                body: JSON.stringify({username: $("username").value.trim(), password: password.value}),
            });
            password.value = "";
            if (register) { setMode(false); message.textContent = "账号已创建，请输入密码登录。"; password.focus(); }
            else { location.replace("/"); }
        } catch (error) {
            message.textContent = error.name === "AbortError"
                ? register ? "等待超时。如果账号已创建，可以返回登录页尝试登录。" : "等待超时，请稍后再试。"
                : error instanceof TypeError ? "连接中断，请检查服务是否正常运行。" : error.message;
        } finally { button.disabled = false; toggle.disabled = false; }
    });
    window.addEventListener("pageshow", event => { if (event.persisted) { password.value = ""; } });
    void connect();
})();
