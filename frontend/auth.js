const authForm = document.querySelector("#authForm");
const registerButton = document.querySelector("#registerButton");
const authStatus = document.querySelector("#authStatus");

function setStatus(message, tone = "neutral") {
  authStatus.textContent = message;
  authStatus.dataset.tone = tone;
}

async function submitAuth(mode) {
  const username = document.querySelector("#username").value.trim();
  const password = document.querySelector("#password").value;
  setStatus(mode === "login" ? "Signing in..." : "Creating account...");

  const response = await fetch(`/auth/${mode}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  const data = await response.json();

  if (!response.ok) {
    const detail = data.detail || "Authentication failed.";
    const friendly =
      detail.toLowerCase().includes("already exists")
        ? "That username already exists. Use Log in, or choose a different username."
        : detail;
    setStatus(friendly, "error");
    return;
  }

  localStorage.setItem("shl_user", JSON.stringify(data));
  setStatus(`Signed in as ${data.username}. Redirecting...`, "success");
  window.location.href = "/chatbot";
}

authForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  await submitAuth("login");
});

registerButton.addEventListener("click", async () => {
  await submitAuth("register");
});
