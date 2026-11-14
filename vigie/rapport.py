"""Sorties : alertes.json, alertes.csv, rapport.html (lisible par le gestionnaire)."""
import csv
import html
import json

COULEURS = {
    "Critique": ("#B42318", "#FFFFFF"),
    "Élevée": ("#FEF0C7", "#7A2E0E"),
    "Modérée": ("#E8EEF9", "#1E3A8A"),
    "Données": ("#EEF0F3", "#374151"),
}
CHAMPS = ["rang", "gravite", "immeuble", "adresse", "fluide", "titre", "constat", "consigne", "prestataire",
          "delai", "payeur", "persistance", "debut", "chiffrage", "periode",
          "kwh_mois", "m3_mois", "chf_mois", "co2_t_mois",          # rythme par 30 jours, tous fluides
          "kwh_an", "m3_an", "chf_an", "co2_t_an",                  # eau et électricité (= projection, dérive constante)
          "kwh_mesure", "m3_mesure", "chf_mesure", "co2_t_mesure",  # dérive constatée depuis le début (tous)
          "kwh_proj", "m3_proj", "chf_proj", "co2_t_proj", "projection",  # projection 12 mois (hypothèse)
          "heures_mesurees", "confiance", "score", "id"]


def ecrire(alertes, fin, dossier):
    with open(f"{dossier}/alertes.json", "w", encoding="utf-8") as f:
        json.dump({"date_analyse": str(fin), "alertes": alertes}, f, ensure_ascii=False, indent=2, default=str)
    with open(f"{dossier}/alertes.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CHAMPS, extrasaction="ignore", delimiter=";")
        w.writeheader()
        w.writerows(alertes)
    with open(f"{dossier}/rapport.html", "w", encoding="utf-8") as f:
        f.write(_html(alertes, fin))


def _fmt(n):
    return f"{n:,.0f}".replace(",", " ")


def _fmt1(n):
    return f"{n:,.1f}".replace(",", " ").replace(".", ",")


def enjeu(a):
    """(montant principal, précisions) d'une alerte : d'abord la dérive CONSTATÉE (mesurée, base des actions), puis le
    rythme mensuel (priorisation), puis la PROJECTION si rien n'est fait, étiquetée avec son hypothèse."""
    if a["gravite"] == "Données":
        return "—", []
    if a.get("chf_mesure") is None:  # alerte enregistrée par une version antérieure du moteur
        return (f"≈ {_fmt(a['chf_an'])} CHF/an" if a.get("chf_an") is not None else "—"), []
    principal = f"Dérive constatée : ≈ {_fmt(a['chf_mesure'])} CHF"
    quantites = [x for x in (f"{_fmt(a['kwh_mesure'])} kWh" if a.get("kwh_mesure") else None,
                             f"{_fmt1(a['m3_mesure'])} m³" if a.get("m3_mesure") else None) if x]
    details = [(" · ".join(quantites) + " " if quantites else "") + a["periode"],
               f"rythme ≈ {_fmt(a['chf_mois'])} CHF/mois (sur {a.get('jours_rythme') or a.get('persistance') or '—'} jours)"]
    if a.get("chf_proj") is not None:
        details.append(f"Projection si rien n'est fait : ≈ {_fmt(a['chf_proj'])} CHF {a['projection']}")
    elif a.get("projection"):
        details.append(f"Projection {a['projection']}")
    return principal, details


def _html(alertes, fin):
    e = html.escape
    metier = [a for a in alertes if a["gravite"] != "Données"]
    total = lambda cle: sum(a.get(cle) or 0 for a in metier)  # noqa: E731
    cartes = []
    for a in alertes:
        bg, fg = COULEURS[a["gravite"]]
        impact, details = enjeu(a)
        if a["sinistre"]:
            details.append("risque de sinistre")
        cartes.append(f"""
<article class="carte">
  <div class="rang">{a['rang']}</div>
  <div class="corps">
    <div class="tags"><span class="chip" style="background:{bg};color:{fg}">{e(a['gravite'])}</span>
      <span class="tag">{e(a['fluide'])}</span>
      <span class="muted">{e(a['persistance'] or '')}{' · confiance ' + format(a['confiance'], '.0%') if a['gravite'] != 'Données' else ''}</span></div>
    <h2>{e(a['titre'])}</h2>
    <p class="muted">{e(a['immeuble'])} · {e(a['adresse'])} · profil {e(a['profil'])}</p>
    <p>{e(a['constat'])}</p>
    <p class="consigne"><strong>Consigne — {e(a['prestataire'])}, sous {e(a['delai'])} :</strong> {e(a['consigne'])}</p>
  </div>
  <div class="impact"><strong>{e(impact)}</strong><span class="muted">{e(' · '.join(details))}</span>
    <span class="muted">Payé par : {e(a['payeur'])}</span></div>
</article>""")
    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><title>Vigie — alertes au {e(str(fin))}</title>
<style>
body{{margin:0;font-family:Inter,system-ui,sans-serif;background:#F5F6F8;color:#111827}}
header{{background:#0F1B2D;color:#fff;padding:16px 32px;font-weight:700;font-size:18px}}
main{{max-width:1200px;margin:0 auto;padding:24px 32px 48px;display:flex;flex-direction:column;gap:16px}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}}
.kpi{{background:#fff;border:1px solid #E3E6EB;border-radius:12px;padding:14px 18px}}
.kpi b{{display:block;font-size:24px;margin-top:4px}}
.carte{{background:#fff;border:1px solid #E3E6EB;border-radius:12px;padding:16px 20px;display:flex;flex-wrap:wrap;gap:16px}}
.rang{{width:32px;height:32px;border-radius:16px;background:#EEF0F3;display:flex;align-items:center;justify-content:center;font-weight:700}}
.corps{{flex:1 1 520px;min-width:0}} .corps h2{{font-size:17px;margin:8px 0 4px}} .corps p{{margin:6px 0;font-size:14px;line-height:1.5}}
.impact{{flex:0 0 220px;display:flex;flex-direction:column;gap:4px;text-align:right}} .impact strong{{font-size:18px}}
.chip{{font-size:12px;font-weight:700;padding:3px 8px;border-radius:6px}} .tag{{font-size:12px;font-weight:600;background:#F1F3F6;padding:3px 8px;border-radius:6px}}
.tags{{display:flex;flex-wrap:wrap;gap:8px;align-items:center}} .muted{{color:#4B5563;font-size:13px}}
.consigne{{background:#F7F8FA;border:1px solid #E3E6EB;border-radius:8px;padding:8px 10px}}
</style></head><body>
<header>Vigie · Détecteur de dérives — analyse au {e(str(fin))} (UTC)</header>
<main>
<div class="kpis">
 <div class="kpi">Alertes ouvertes<b>{len(alertes)}</b><span class="muted">dont {sum(a['gravite'] == 'Critique' for a in alertes)} critiques</span></div>
 <div class="kpi">Rythme des dérives<b>≈ {_fmt(total('chf_mois'))} CHF/mois</b><span class="muted">tous fluides, aux conditions actuelles · tarifs d'exemple</span></div>
 <div class="kpi">Dérives constatées<b>≈ {_fmt(total('chf_mesure'))} CHF</b><span class="muted">excès mesuré depuis le début des dérives</span></div>
 <div class="kpi">Projection si rien n'est fait<b>≈ {_fmt(total('chf_proj'))} CHF</b><span class="muted">12 mois, hypothèses : climat normal, dérive constante</span></div>
 <div class="kpi">Énergie en dérive<b>≈ {_fmt1(total('kwh_mois') / 1000)} MWh/mois</b><span class="muted">et ≈ {_fmt(total('m3_mois'))} m³ d'eau par mois</span></div>
 <div class="kpi">Émissions évitables<b>≈ {_fmt1(total('co2_t_mois'))} t CO₂/mois</b><span class="muted">facteurs d'exemple</span></div>
</div>
{''.join(cartes)}
</main></body></html>"""
