const baseRenderCaseReviewEmail=renderCaseReview,baseShowReviewSectionEmail=showReviewSection;
function isEmailCase(investigation){return investigation?.audits?.some(audit=>audit?.audit_type==='email')}
function emailSocialProfiles(items){return items.filter(item=>/social|professional|video|creative|community|blog/.test(String(item?.category||'')))}
function emailSubject(investigation){return investigation?.subject||investigation?.title||''}
renderCaseReview=function(investigation){
  if(!isEmailCase(investigation))return baseRenderCaseReviewEmail(investigation);
  const data=usernameReviewData(investigation),tr=language==='tr',sections=['email-overview','email-profiles','email-social','email-diagnostics'],labels={"email-overview":tr?'Genel Bakış':'Overview',"email-profiles":tr?'Bağlı profiller':'Linked profiles',"email-social":tr?'Sosyal hesaplar':'Social accounts',"email-diagnostics":tr?'Kaynak durumları':'Source statuses'},social=emailSocialProfiles(data.profiles),counts={"email-overview":'',"email-profiles":data.profiles.length,"email-social":social.length,"email-diagnostics":data.diagnostics.length};
  $('#reviewTitle').textContent=tr?'E-posta İnceleme Merkezi':'Email Review Center';
  $('#copyCaseJson').textContent=tr?'DOSYA JSON KOPYALA':'COPY CASE JSON';
  $('#detailWorkspaceNav').innerHTML=`<div class="workspace-nav-title"><small>${tr?'AKTİF SORUŞTURMA':'ACTIVE INVESTIGATION'}</small><b>${esc(emailSubject(investigation))}</b></div>${sections.map((key,index)=>`<button data-review-key="${key}" class="${index===0?'active':''}"><span>${String(index+1).padStart(2,'0')}</span>${labels[key]}<em>${counts[key]}</em></button>`).join('')}`;
  $$('#detailWorkspaceNav button').forEach(button=>button.onclick=()=>showReviewSection(investigation,button.dataset.reviewKey));
  showReviewSection(investigation,'email-overview');
};
showReviewSection=function(investigation,key){
  if(!isEmailCase(investigation)||!key.startsWith('email-'))return baseShowReviewSectionEmail(investigation,key);
  const data=usernameReviewData(investigation),content=$('#detailWorkspaceContent'),tr=language==='tr',subject=emailSubject(investigation),social=emailSocialProfiles(data.profiles),head=title=>`<div class="username-review-head"><small>EMAIL INTELLIGENCE</small><h1>${title}</h1></div>`;
  if(key==='email-overview')content.innerHTML=head(esc(subject))+`<div class="username-metrics"><span><b>${data.profiles.length}</b>${tr?'Bağlı profil':'Linked profiles'}</span><span><b>${data.profiles.filter(x=>x.status==='confirmed').length}</b>${tr?'Doğrulanmış':'Confirmed'}</span><span><b>${social.length}</b>${tr?'Sosyal hesap':'Social accounts'}</span><span><b>${data.profiles.filter(x=>!['confirmed','probable'].includes(x.status)).length}</b>${tr?'Doğrulanmamış':'Unverified'}</span></div>`;
  else if(key==='email-profiles')content.innerHTML=head(tr?'Bağlı profiller':'Linked profiles')+usernameProfileCards(data.profiles);
  else if(key==='email-social')content.innerHTML=head(tr?'Sosyal hesaplar':'Social accounts')+usernameProfileCards(social);
  else content.innerHTML=head(tr?'Kaynak durumları':'Source statuses')+usernameDiagnosticsCards(data.diagnostics);
  $$('#detailWorkspaceNav button').forEach(button=>button.classList.toggle('active',button.dataset.reviewKey===key));content.scrollTop=0;
};
