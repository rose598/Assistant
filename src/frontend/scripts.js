/* 聊天界面逻辑: 发送问题到 /api/ask, 渲染 Markdown 与代码高亮. */

(function () {
    "use strict";

    var messagesEl = document.getElementById("messages");
    var form = document.getElementById("ask-form");
    var input = document.getElementById("question");

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

    async function ask(question) {
        addMessage("user", question);
        addTyping();
        input.value = "";
        try {
            var resp = await fetch("/api/ask", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ question: question })
            });
            removeTyping();
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
            var text = data.answer || "(无回答)";
            var reply = text;
            if (data.sources && data.sources.length) {
                reply += "\n\n**参考来源**: " + data.sources.join("、");
            }
            var botMsg = addMessage("bot", reply);
            addFeedback(botMsg, question, data.answer || "");
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