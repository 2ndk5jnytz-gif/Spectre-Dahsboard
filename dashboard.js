function showToast(message, ok = true) {
    const toast = document.getElementById("toast");
    toast.textContent = message;
    toast.className = "toast show " + (ok ? "ok" : "err");
    setTimeout(() => { toast.className = "toast"; }, 3200);
}

const GUILD_ID = window.location.pathname.split("/")[2];

async function saveSettings(data) {
    try {
        const response = await fetch(`/dashboard/${GUILD_ID}/save-settings`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data),
        });
        const result = await response.json();
        showToast(result.ok ? "✅ تم الحفظ فوراً وانربط بالبوت." : ("❌ " + (result.error || "فشل الحفظ")), result.ok);
        return result;
    } catch (error) {
        showToast("❌ تعذّر الاتصال باللوحة", false);
    }
}

async function callAction(name, payload) {
    try {
        const response = await fetch(`/dashboard/${GUILD_ID}/action/${name}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        const result = await response.json();
        showToast(result.ok ? "✅ تم التنفيذ فوراً على البوت." : ("❌ " + (result.error || "فشل التنفيذ")), result.ok);
        return result;
    } catch (error) {
        showToast("❌ تعذّر الاتصال باللوحة", false);
    }
}

function collectForm(formEl) {
    const data = {};
    formEl.querySelectorAll("[data-key]").forEach((el) => {
        data[el.dataset.key] = el.type === "checkbox" ? (el.checked ? "1" : "0") : el.value;
    });
    return data;
}
