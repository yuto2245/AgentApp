// 認証フォームのバリデーションと補助機能
document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("signupForm");
  const emailInput = document.getElementById("email");
  const displayNameInput = document.getElementById("displayName");
  const passwordInput = document.getElementById("password");
  const emailError = document.getElementById("emailError");
  const passwordError = document.getElementById("passwordError");
  const statusEl = document.getElementById("signupStatus");
  const passwordVisibilityButton = document.getElementById("passwordVisibilityButton");
  const passwordIcon = passwordVisibilityButton?.querySelector(".material-symbols-outlined");

  if (!emailInput || !passwordInput || !emailError || !passwordError) {
    // TODO: 画面構成が変わった場合に備えたフォールバックが必要なら実装する
    return;
  }

  emailInput.addEventListener("input", () => {
    const { valid, message } = validateEmail(emailInput.value);
    emailError.textContent = valid ? "" : message;
  });

  passwordInput.addEventListener("input", () => {
    const { valid, message } = validatePassword(passwordInput.value);
    passwordError.textContent = valid ? "" : message;
  });

  passwordVisibilityButton?.addEventListener("click", () => {
    if (!passwordInput) {
      return;
    }
    const hidden = passwordInput.type === "password";
    passwordInput.type = hidden ? "text" : "password";
    if (passwordIcon) {
      passwordIcon.textContent = hidden ? "visibility_off" : "visibility";
    }
  });

  form?.addEventListener("submit", async (event) => {
    event.preventDefault();

    const emailResult = validateEmail(emailInput.value);
    const passwordResult = validatePassword(passwordInput.value);

    emailError.textContent = emailResult.valid ? "" : emailResult.message;
    passwordError.textContent = passwordResult.valid ? "" : passwordResult.message;

    if (!emailResult.valid || !passwordResult.valid) {
      if (statusEl) {
        statusEl.textContent = "";
      }
      return;
    }

    const payload = {
      email: emailInput.value.trim(),
      password: passwordInput.value,
      display_name: displayNameInput ? displayNameInput.value.trim() : emailInput.value.trim(),
    };

    try {
      const res = await fetch("/api/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      const data = await res.json().catch(() => ({}));

      if (res.ok) {
        if (statusEl) {
          statusEl.textContent = "登録が完了しました。ログインしてください。";
          statusEl.className = "text-success text-center mt-3";
        }
        form.reset();
      } else {
        if (statusEl) {
          statusEl.textContent = data.detail || "登録できませんでした。";
          statusEl.className = "text-danger text-center mt-3";
        }
      }
    } catch (error) {
      if (statusEl) {
        statusEl.textContent = "通信中にエラーが発生しました。";
        statusEl.className = "text-danger text-center mt-3";
      }
    }
  });
});

/*メールアドレスのバリデーション*/
function validateEmail(rawValue) {
  const value = rawValue.trim();
  if (value.length === 0) {
    return { valid: false, message: "メールアドレスが入力されていません" };
  }

  const atIndex = value.indexOf("@");
  const lastAtIndex = value.lastIndexOf("@");
  const lastDotIndex = value.lastIndexOf(".");

  const hasSingleAt = atIndex > 0 && atIndex === lastAtIndex;
  const hasDotAfterAt = lastDotIndex > atIndex + 1 && lastDotIndex < value.length - 1;
  const localPart = value.slice(0, atIndex);
  const domainPart = value.slice(atIndex + 1);

  if (!hasSingleAt || !hasDotAfterAt || localPart.length === 0 || domainPart.length === 0) {
    return { valid: false, message: "メールアドレスの形式が正しくありません" };
  }

  // TODO: さらに厳密なバリデーション（例: ドメイン正規表現、IDN対応）が必要ならここに追加する
  return { valid: true, message: "" };
}

function validatePassword(value) {
  if (!value || value.length === 0) {
    return { valid: false, message: "パスワードが入力されていません" };
  }
  if (value.length < 8) {
    return { valid: false, message: "パスワードは8文字以上で入力してください" };
  }
  if (!/[a-z]/.test(value)) {
    return { valid: false, message: "パスワードには小文字が含まれていません" };
  }
  if (!/[A-Z]/.test(value)) {
    return { valid: false, message: "パスワードには大文字が含まれていません" };
  }
  if (!/[0-9]/.test(value)) {
    return { valid: false, message: "パスワードには数字が含まれていません" };
  }
  if (!/[!@#$%^&*]/.test(value)) {
    return { valid: false, message: "パスワードには記号が含まれていません" };
  }

  return { valid: true, message: "" };
}
