// Fiction intégrale. 30 jours, référence normalisée à 1 000 kWh/j.
// Dérive de +40 % durant les 15 derniers jours = 6 000 kWh, soit +20 % du mois.
export const reference = Array.from({length:30}, () => 1000);
export const actual = reference.map((v,i) => v + (i >= 15 ? 400 : 0));
export const expectedKwh = reference.reduce((a,b)=>a+b,0);
export const measuredKwh = actual.reduce((a,b)=>a+b,0);
export const excessKwh = measuredKwh - expectedKwh;
export const tariff = 0.18;
export const costCHF = excessKwh * tariff;
export const buildings = [
  {name:'École des Cèdres', type:'Chauffage · référence météo', status:'Élevée', kwh:6000, cost:1080},
  {name:'Ateliers du Parc', type:'Électricité · puissance de nuit', status:'Modérée', kwh:1500, cost:270},
  {name:'Résidence du Lac', type:'Chauffage · signature météo', status:'Conforme', kwh:0, cost:0},
];
