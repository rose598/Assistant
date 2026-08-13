/* 聊天界面逻辑: 发送问题到 /api/ask, 渲染 Markdown 与代码高亮. */

(function () {
    "use strict";

    var messagesEl = document.getElementById("messages");
    var form = document.getElementById("ask-form");
    var input = document.getElementById("question");

    // 会话 ID: 首次生成并持久化到 localStorage, 多轮对话保持同一 session
    var sessionId = localStorage.getItem("ask_session_id");
    if (!sessionId) {
        sessionId = "web-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 8);
        localStorage.setItem("ask_session_id", sessionId);
    }

    // marked 配置: 启用 GFM, 代码高亮交给 highlight 处理
    if (window.marked) {
        marked.setOptions({ gfm: true, breaks: true });
    }

    function escapeHtml(s) {
        var div = document.createElement("div");
        div.textContent = s == null ? "" : String(s);
        return div.innerHTML;
    }

    function addMessage(role, content) {
        var msg = document.createElement("div");
        msg.className = "msg " + role;
        var bubble = document.createElement("div");
        bubble.className = "bubble";
        if (role === "user") {
            bubble.textContent = content;
        } else {
            bubble.innerHTML = renderMarkdown(content);
        }
        msg.appendChild(bubble);
        messagesEl.appendChild(msg);
        // 高亮代码块
        if (role === "bot" && window.hljs) {
            bubble.querySelectorAll("pre code").forEach(function (el) {
                hljs.highlightElement(el);
            });
        }
        scrollToBottom();
        return msg;
    }

    function renderMarkdown(text) {
        if (window.marked) {
            try {
                return marked.parse(text || "");
            } catch (e) {
                return escapeHtml(text);
            }
        }
        return escapeHtml(text);
    }

    // 在一条 bot 回答底部追加"有用/无用"反馈按钮
    function addFeedback(msgEl, question, answer) {
        var row = document.createElement("div");
        row.className = "feedback-btns";
        row.innerHTML =
            '<button type="button" data-v="1">👍 有用</button>' +
            '<button type="button" data-v="0">👎 无用</button>';
        msgEl.appendChild(row);
        row.querySelectorAll("button").forEach(function (btn) {
            btn.addEventListener("click", function () {
                sendFeedback(btn, question, answer, btn.getAttribute("data-v") === "1");
            });
        });
    }

    // 提交反馈到 /api/feedback, 成功后禁用该组按钮并显示状态
    function sendFeedback(btn, question, answer, useful) {
        fetch("/api/feedback", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ useful: useful ? 1 : 0, question: question, answer: answer })
        }).then(function (r) {
            if (!r.ok) { throw new Error("status " + r.status); }
            var group = btn.parentElement;
            group.querySelectorAll("button").forEach(function (b) { b.disabled = true; });
            var status = document.createElement("span");
            status.className = "feedback-status";
            status.textContent = "已记录，谢谢反馈";
            group.appendChild(status);
        }).catch(function () {
            alert("反馈提交失败，请重试");
        });
    }

    function addTyping() {
        var msg = document.createElement("div");
        msg.className = "msg bot typing";
        msg.id = "typing";
        var bubble = document.createElement("div");
        bubble.className = "bubble";
        msg.appendChild(bubble);
        messagesEl.appendChild(msg);
        scrollToBottom();
        return msg;
    }

    function removeTyping() {
        var t = document.getElementById("typing");
        if (t) { t.remove(); }
    }

    function scrollToBottom() {
        var chat = document.querySelector(".chat");
        chat.scrollTop = chat.scrollHeight;
    }

    // 解析 SSE 事件流: 逐段 (data:) 文本, 返回事件数组
    async function readSse(resp) {
        var reader = resp.body.getReader();
        var decoder = new TextDecoder("utf-8");
        var buffer = "";
        var events = [];
        while (true) {
            var r = await reader.read();
            if (r.done) { break; }
            buffer += decoder.decode(r.value, { stream: true });
            var lines = buffer.split("\n");
            buffer = lines.pop(); // 保留未以换行结尾的残片
            for (var i = 0; i < lines.length; i++) {
                var line = lines[i];
                if (line.indexOf("data:") !== 0) { continue; }
                var payload = line.slice(5).trim();
                if (payload === "[DONE]") { return events; }
                try { events.push(JSON.parse(payload)); } catch (e) { /* 忽略 */ }
            }
        }
        return events;
    }

    // 尝试流式问答; 失败(如接口不可用)时回退到非流式 POST
    async function askStream(question, botMsg) {
        var resp = await fetch("/api/ask/stream", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ question: question, session_id: sessionId })
        });
        if (!resp.ok || !resp.body) { return null; }
        var events = await readSse(resp);
        var parts = [];
        events.forEach(function (ev) {
            if (ev.type === "token") { parts.push(ev.content || ""); }
        });
        var text = parts.join("");
        // 逐段渲染(打字机效果): 直接渲染累积文本
        if (text) { botMsg.querySelector(".bubble").innerHTML = renderMarkdown(text); }
        return text;
    }

    async function ask(question) {
        addMessage("user", question);
        var botMsg = addTyping();
        input.value = "";
        var fullAnswer = "";
        try {
            var streamed = await askStream(question, botMsg);
            removeTyping();
            if (streamed) {
                fullAnswer = streamed;
            } else {
                // 回退: 非流式 POST /api/ask
                removeTyping();
                var resp = await fetch("/api/ask", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ question: question, session_id: sessionId })
                });
                if (!resp.ok) {
                    var detail = "请求失败 (" + resp.status + ")";
                    try {
                        var j = await resp.json();
                        if (j && j.detail) { detail = j.detail; }
                    } catch (e) { /* 忽略 */ }
                    addMessage("bot", "⚠️ " + detail);
                    return;
                }
                var data = await resp.json();
                fullAnswer = data.answer || "(无回答)";
                var reply = fullAnswer;
                if (data.sources && data.sources.length) {
                    reply += "\n\n**参考来源**: " + data.sources.join("、");
                }
                botMsg.querySelector(".bubble").innerHTML = renderMarkdown(reply);
            }
            // 高亮重置(逐段渲染可能丢失 hljs 标注)
            if (window.hljs && botMsg) {
                botMsg.querySelectorAll("pre code").forEach(function (el) {
                    hljs.highlightElement(el);
                });
            }
            addFeedback(botMsg, question, fullAnswer);
        } catch (err) {
            removeTyping();
            addMessage("bot error", "⚠️ 网络错误，无法连接到服务器。");
        } finally {
            input.focus();
        }
    }

    form.addEventListener("submit", function (e) {
        e.preventDefault();
        var q = input.value.trim();
        if (!q) { return; }
        ask(q);
    });
})();