const savedUser = JSON.parse(localStorage.getItem("shl_user") || "null");

if (savedUser) {
  document.querySelectorAll('a[href="/login"]').forEach((link) => {
    link.textContent = "Go to chatbot";
    link.href = "/chatbot";
  });
}
