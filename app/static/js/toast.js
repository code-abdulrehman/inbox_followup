function showToast(message, type, duration) {
  type = type || 'info';
  duration = duration || 4000;

  var container = document.getElementById('toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toast-container';
    container.className = 'toast-container';
    document.body.appendChild(container);
  }

  var toast = document.createElement('div');
  toast.className = 'toast toast-' + type;

  var icons = { success: iconSVG('check'), error: iconSVG('x'), warning: iconSVG('warning'), info: iconSVG('info') };
  toast.innerHTML = '<span>' + (icons[type] || '') + '</span> <span>' + message + '</span> <button class="toast-dismiss" onclick="this.parentElement.remove()">×</button>';

  container.appendChild(toast);

  var timeout = setTimeout(function () {
    toast.style.animation = 'toast-out 0.3s ease forwards';
    setTimeout(function () { toast.remove(); }, 300);
  }, duration);

  toast.addEventListener('click', function () {
    clearTimeout(timeout);
    toast.style.animation = 'toast-out 0.3s ease forwards';
    setTimeout(function () { toast.remove(); }, 300);
  });
}
