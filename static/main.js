function fav(id, btn){
  fetch(`/fav/${id}`, {method:'POST'}).then(r=>r.json()).then(d=>{
    if(d.ok){ btn.classList.toggle('on');
      btn.textContent = btn.classList.contains('on') ? '⭐ 已收藏' : '☆ 收藏'; }
  });
}
