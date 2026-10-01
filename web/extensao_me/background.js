// Extensão "CotaFrete - Abrir no ME" (web/me_extensao.py gera o pacote).
//
// A página do CotaFrete manda só {cid}. A extensão busca a sessão DIRETO no
// CotaFrete, com o login do vendedor — o JavaScript da página nunca vê a
// sessão do ME —, troca os dois cookies da sessão do ME e abre a cotação.
// Só páginas do endereço do CotaFrete conseguem chamar (externally_connectable
// no manifesto, gerado com o endereço de quem baixou).
const ME = "https://www.me.com.br";
const SESSAO = ["ASP.NET_SessionId", "ME"];

chrome.runtime.onMessageExternal.addListener((msg, sender, responder) => {
  (async () => {
    try {
      const cid = Number(msg && msg.cid);
      if (!Number.isInteger(cid) || cid <= 0) throw new Error("cotação inválida");
      const origem = new URL(sender.url).origin;
      const r = await fetch(`${origem}/me/${cid}/sessao-me`, {method: "POST", credentials: "include"});
      const dados = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(dados.erro || ("o CotaFrete recusou (" + r.status + ")"));
      if (typeof dados.url !== "string" || !dados.url.startsWith(ME + "/")) throw new Error("endereço fora do ME");
      for (const c of await chrome.cookies.getAll({domain: "me.com.br"})) {
        if (SESSAO.includes(c.name)) {
          await chrome.cookies.remove({url: "https://" + c.domain.replace(/^\./, "") + c.path, name: c.name});
        }
      }
      for (const c of dados.cookies) {
        if (!SESSAO.includes(c.name)) continue;
        await chrome.cookies.set({url: ME + "/", name: c.name, value: c.value, path: c.path || "/",
                                  secure: true, httpOnly: true,
                                  expirationDate: c.expires > 0 ? c.expires : undefined});
      }
      await chrome.tabs.create({url: dados.url});
      responder({ok: true});
    } catch (e) {
      responder({ok: false, erro: String(e && e.message || e)});
    }
  })();
  return true;  // resposta assíncrona
});
