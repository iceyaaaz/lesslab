// 令牌由 HttpOnly Cookie 持有；这里只在内存中保存当前会话的 CSRF 校验值。
(() => {
    const nativeFetch = window.fetch.bind(window);
    const name = document.getElementById("account-name");
    const logout = document.getElementById("logout-button");
    let identity = null;
    let csrf = null;
    let leaving = false;
    function goToLogin() {
        leaving = true;
        location.replace("/login");
    }
    async function checkSession() {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 15000);
        try {
            const response = await nativeFetch("/auth/me", {signal: controller.signal, cache: "no-store"});
            if (response.status === 401) { goToLogin(); throw new Error("请重新登录。"); }
            if (!response.ok) throw new Error("暂时无法验证登录，请刷新页面重试。");
            const data = await response.json();
            if (!Number.isInteger(data.id) || typeof data.csrf_token !== "string") throw new Error("登录信息异常，请重新登录。");
            if (identity !== null && identity !== data.id) {
                goToLogin();
                throw new Error("账号已在其他窗口变化，请重新打开页面。");
            }
            identity = data.id;
            csrf = data.csrf_token;
            name.textContent = data.username;
        } finally { clearTimeout(timer); }
    }
    const ready = checkSession();
    ready.catch(() => { name.textContent = "登录验证失败，请刷新页面"; });

    window.fetch = async (input, options = {}) => {
        const url = new URL(input instanceof Request ? input.url : input, location.href);
        if (url.origin !== location.origin) return nativeFetch(input, options);
        await ready;
        if (leaving) throw new Error("请重新登录。");
        const method = (options.method || (input instanceof Request ? input.method : "GET")).toUpperCase();
        const headers = new Headers(options.headers || (input instanceof Request ? input.headers : undefined));
        if (!["GET", "HEAD", "OPTIONS"].includes(method)) headers.set("X-CSRF-Token", csrf);
        const response = await nativeFetch(input, {...options, headers, credentials: "same-origin"});
        if (response.status === 401) goToLogin();
        return response;
    };

    logout.addEventListener("click", async () => {
        if (logout.disabled) return;
        logout.disabled = true;
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 15000);
        try {
            const response = await fetch("/auth/logout", {method: "POST", signal: controller.signal});
            if (!response.ok) throw new Error("退出未完成，请重试或刷新页面。");
            goToLogin();
        } catch (error) { name.textContent = error.name === "AbortError" ? "退出请求超时，请刷新页面确认登录状态。" : error.message; }
        finally { clearTimeout(timer); logout.disabled = false; }
    });
    window.addEventListener("pageshow", event => { if (event.persisted) location.reload(); });
    window.addEventListener("focus", () => {
        if (!leaving && identity !== null) void checkSession().catch(() => { name.textContent = "登录验证失败，请刷新页面"; });
    });
})();
