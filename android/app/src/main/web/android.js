/* Android-only integration; all wiki data still runs from the bundled archive. */
'use strict';
(() => {
  const native = window.AndroidOffline;
  if (!native || window.WikiAndroid) return;
  const origin = 'https://appassets.androidplatform.net';
  const objects = new Map();
  const create = URL.createObjectURL.bind(URL), revoke = URL.revokeObjectURL.bind(URL);
  URL.createObjectURL = blob => {const url=create(blob);objects.set(url,blob);return url;};
  URL.revokeObjectURL = url => {objects.delete(url);revoke(url);};
  function message(text) {
    const box=document.getElementById('toast');
    if (box) {box.textContent=text;box.classList.add('show');setTimeout(()=>box.classList.remove('show'),3500);}
  }
  function download(anchor) {
    if (!anchor.hasAttribute('download')) return false;
    const url=new URL(anchor.href,location.href);
    const name=anchor.download || decodeURIComponent(url.pathname.split('/').pop()) || '铃兰档案馆图片.webp';
    const blob=objects.get(anchor.href);
    if (blob) {
      if (blob.size>64*1024*1024) {message('文件超过 64 MB，请缩小画布尺寸后保存。');return true;}
      const reader=new FileReader();
      reader.onload=()=>native.saveBase64(name,blob.type||'application/octet-stream',String(reader.result).split(',')[1]);
      reader.onerror=()=>message('读取导出内容失败，请重试。');
      reader.readAsDataURL(blob);
      return true;
    }
    if (url.origin===origin && url.pathname.startsWith('/assets/wiki/assets/')) {
      native.saveAsset(url.href,name);return true;
    }
    message('无法保存此文件，请选择本地资料图片。');return true;
  }
  const click=HTMLAnchorElement.prototype.click;
  HTMLAnchorElement.prototype.click=function(){if(!download(this))click.call(this);};
  document.addEventListener('click',event=>{
    const anchor=event.target.closest?.('a[href]');
    if(!anchor)return;
    if(download(anchor)){event.preventDefault();event.stopImmediatePropagation();return;}
    const url=new URL(anchor.href,location.href);
    if(/^https?:$/.test(url.protocol)&&url.origin!==origin){event.preventDefault();event.stopImmediatePropagation();native.openExternal(url.href);}
  },true);
  window.WikiAndroid=Object.freeze({
    back(){
      const dialog=document.querySelector('dialog[open]');
      if(dialog){dialog.close();return true;}
      if(document.body.classList.contains('nav-open')){document.body.classList.remove('nav-open');return true;}
      if(document.body.classList.contains('reading')){document.body.classList.remove('reading');return true;}
      return false;
    },
    message
  });
  const syncTheme=()=>native.setDarkTheme(document.body.classList.contains('dark'));
  const ready=()=>{
    syncTheme();new MutationObserver(syncTheme).observe(document.body,{attributes:true,attributeFilter:['class']});
    // Keep the archive description accurate inside the installed app.
    const adapt=()=>{
      document.querySelectorAll('.archive-row').forEach(row=>{
        if(row.firstElementChild?.textContent==='离线方式')row.lastElementChild.textContent='APK 内置资料，无需联网';
      });
      document.querySelectorAll('.archive-copy p,.notes-box small,.pity-card+section>small').forEach(el=>{
        el.textContent.includes('当前浏览器')&&(el.innerHTML=el.innerHTML.replaceAll('当前浏览器','本机应用'));
      });
    };
    new MutationObserver(adapt).observe(document.getElementById('main'),{childList:true});adapt();
  };
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',ready);else ready();
})();
