/*
 * Chat UI.
 *
 * The JWT is held in a module-scoped variable only — not localStorage, not a cookie — so it
 * disappears on refresh. Fine for a demo; httpOnly cookies are the production answer.
 */
(function () {
  "use strict";

  let token = null;
  let studentId = null;
  const sessionId = "SESSION-" + Math.random().toString(36).slice(2, 8).toUpperCase();

  const loginView = document.getElementById("loginView");
  const chatView = document.getElementById("chatView");
  const loginForm = document.getElementById("loginForm");
  const loginError = document.getElementById("loginError");
  const loginBtn = document.getElementById("loginBtn");
  const chatForm = document.getElementById("chatForm");
  const messageInput = document.getElementById("message");
  const sendBtn = document.getElementById("sendBtn");
  const messages = document.getElementById("messages");
  const who = document.getElementById("who");
  const whoLabel = document.getElementById("whoLabel");

  document.getElementById("sessionLabel").textContent = sessionId;

  function addMessage(text, kind) {
    const el = document.createElement("div");
    el.className = "msg " + kind;
    el.textContent = text;
    messages.appendChild(el);
    messages.scrollTop = messages.scrollHeight;
    return el;
  }

  loginForm.addEventListener("submit", async function (event) {
    event.preventDefault();
    loginError.textContent = "";
    loginBtn.disabled = true;
    try {
      const response = await fetch("/api/v1/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: document.getElementById("email").value,
          password: document.getElementById("password").value,
        }),
      });
      const data = await response.json();
      if (!response.ok) {
        loginError.textContent = data.detail || "Sign in failed";
        return;
      }
      token = data.access_token;
      studentId = data.student_id;
      loginView.hidden = true;
      chatView.hidden = false;
      who.hidden = false;
      whoLabel.textContent = studentId;
      messages.innerHTML = "";
      addMessage(
        "Hello! I can help with programs, application deadlines and your application status.",
        "bot"
      );
      messageInput.focus();
    } catch (err) {
      loginError.textContent = "Could not reach the server.";
    } finally {
      loginBtn.disabled = false;
    }
  });

  chatForm.addEventListener("submit", async function (event) {
    event.preventDefault();
    const text = messageInput.value.trim();
    if (!text) return;

    addMessage(text, "user");
    messageInput.value = "";
    sendBtn.disabled = true;
    const pending = addMessage("Thinking…", "bot typing");

    try {
      const response = await fetch("/api/v1/enrollment/chat", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: "Bearer " + token,
        },
        body: JSON.stringify({ session_id: sessionId, message: text }),
      });

      if (response.status === 401) {
        pending.remove();
        addMessage("Your session expired. Please sign in again.", "bot error");
        token = null;
        chatView.hidden = true;
        who.hidden = true;
        loginView.hidden = false;
        return;
      }

      const data = await response.json();
      pending.remove();
      if (!response.ok) {
        addMessage(data.detail || "Something went wrong.", "bot error");
        return;
      }
      const kind =
        data.status === "escalated" ? "bot escalated"
        : data.status === "blocked" ? "bot blocked"
        : data.status === "error" ? "bot error"
        : "bot";
      addMessage(data.message, kind);
    } catch (err) {
      pending.remove();
      addMessage("Could not reach the server.", "bot error");
    } finally {
      sendBtn.disabled = false;
      messageInput.focus();
    }
  });

  document.getElementById("logout").addEventListener("click", function () {
    token = null;
    studentId = null;
    messages.innerHTML = "";
    chatView.hidden = true;
    who.hidden = true;
    loginView.hidden = false;
  });
})();
