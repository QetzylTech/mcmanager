(function () {
  "use strict";

  var steps = Array.prototype.slice.call(document.querySelectorAll(".wizard-step"));
  var backBtn = document.getElementById("setup-back-btn");
  var nextBtn = document.getElementById("setup-next-btn");
  var passwordStatus = document.getElementById("setup-password-status");
  var currentStep = 0;

  if (!steps.length || !backBtn || !nextBtn) return;

  backBtn.addEventListener("click", function () {
    if (currentStep > 0) currentStep -= 1;
    render();
  });

  nextBtn.addEventListener("click", function () {
    if (currentStep === 4) validatePasswords();
    if (currentStep < steps.length - 1) currentStep += 1;
    render();
  });

  render();

  function render() {
    steps.forEach(function (step, index) {
      step.hidden = index !== currentStep;
    });
    backBtn.disabled = currentStep === 0;
    if (currentStep === steps.length - 2) {
      nextBtn.textContent = "Finish";
    } else if (currentStep === steps.length - 1) {
      nextBtn.textContent = "Restart";
      nextBtn.onclick = function () {
        currentStep = 0;
        nextBtn.onclick = null;
        render();
      };
    } else {
      nextBtn.textContent = "Next";
      nextBtn.onclick = null;
    }
    if (currentStep === 5) {
      setTimeout(function () {
        if (currentStep === 5) {
          currentStep = 6;
          render();
        }
      }, 1200);
    }
  }

  function validatePasswords() {
    var a = document.getElementById("setup-admin-password");
    var b = document.getElementById("setup-admin-password-confirm");
    if (!a || !b || !passwordStatus) return;
    if (a.value && a.value === b.value) {
      passwordStatus.textContent = "Passwords match.";
      passwordStatus.style.color = "#166534";
    } else {
      passwordStatus.textContent = "Passwords do not match. Prototype still allows moving forward so you can inspect the flow.";
      passwordStatus.style.color = "#b91c1c";
    }
  }
})();
