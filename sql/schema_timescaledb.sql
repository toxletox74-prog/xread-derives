-- Vigie — schéma cible PostgreSQL + TimescaleDB
-- Le prototype utilise le même modèle sous SQLite (vigie/db.py) pour tourner sans serveur.

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ---------- Référentiel ----------
CREATE TABLE adresse (
    id          TEXT PRIMARY KEY,
    rue         TEXT NOT NULL,
    npa_localite TEXT NOT NULL,
    lat          DOUBLE PRECISION,       -- WGS84 (géocodeur fédéral ou saisie manuelle)
    lon          DOUBLE PRECISION,
    geo_source   TEXT,                   -- geo.admin.ch | manuel | introuvable | exemple | plan
    geo_label    TEXT,
    x_km         DOUBLE PRECISION,       -- position sur le plan d'un jeu fictif (km) : lat / lon en sont calculées, jamais géocodées
    y_km         DOUBLE PRECISION
);

CREATE TABLE immeuble (
    id              TEXT PRIMARY KEY,
    adresse_id      TEXT NOT NULL REFERENCES adresse(id),
    nom             TEXT NOT NULL,
    profil          TEXT NOT NULL CHECK (profil IN ('Habite','Vide','Partiel','Travaux','Fermeture')),
    taux_occupation NUMERIC(4,3),          -- profil Partiel
    logements       INTEGER,
    sre_m2          NUMERIC,                -- surface de référence énergétique (IDC)
    talon_horsgel_kwh_j NUMERIC,            -- profil Vide
    proprietaire    TEXT,
    remarque        TEXT,
    typologie       TEXT,                   -- affectation du site (école, administration, logements communaux…)
    quartier        TEXT
);

-- Bâtiments d'un site (un immeuble Vigie = un site ; ses bâtiments gardent leur identifiant, ex. S01-B1)
CREATE TABLE batiment (
    id                 TEXT PRIMARY KEY,
    immeuble_id        TEXT NOT NULL REFERENCES immeuble(id),
    nom                TEXT NOT NULL,
    annee_construction INTEGER,
    annee_renovation   INTEGER,
    sre_m2             NUMERIC,
    niveaux            INTEGER,
    label              TEXT,
    logements          INTEGER,
    ouverture          TEXT,                -- mois d'ouverture AAAA-MM si le bâtiment ouvre pendant la période
    remarque           TEXT
);

-- Installations techniques d'un site (chaudière, PAC, sous-station, photovoltaïque…)
CREATE TABLE installation (
    id              TEXT PRIMARY KEY,
    immeuble_id     TEXT NOT NULL REFERENCES immeuble(id),
    type            TEXT NOT NULL,
    libelle         TEXT NOT NULL,
    vecteur         TEXT,
    puissance_kw    NUMERIC,                -- kWc pour le photovoltaïque
    mise_en_service TEXT,                   -- AAAA-MM
    retrait         TEXT,                   -- AAAA-MM, vide = en service
    remarque        TEXT
);

-- Références d'un lot : climat mensuel et normale, conversions, facteurs CO2, calendrier du jour
CREATE TABLE reference (
    serie   TEXT NOT NULL,                  -- temperature_moy_c, degres_jours_20_12, conversion_gaz, jour_ouvre…
    periode TEXT NOT NULL,                  -- AAAA-MM, AAAA-MM-JJ, 01 à 12 (normale) ou « toujours »
    valeur  DOUBLE PRECISION NOT NULL,
    unite   TEXT,
    source  TEXT,
    PRIMARY KEY (serie, periode)
);

-- Trace des anomalies relevées à l'import (rien n'est corrigé ni comblé en silence)
CREATE TABLE anomalie_import (
    id         BIGSERIAL PRIMARY KEY,
    lot        TEXT NOT NULL,
    type       TEXT NOT NULL,
    feuille    TEXT,                        -- feuille du classeur ou fichier de courbes
    ligne      INTEGER,
    objet      TEXT,                        -- compteur concerné
    periode    TEXT,
    detail     TEXT NOT NULL,
    traitement TEXT NOT NULL
);

CREATE TABLE point_mesure (
    id          TEXT PRIMARY KEY,
    immeuble_id TEXT REFERENCES immeuble(id),  -- NULL pour la température extérieure du parc
    fluide      TEXT NOT NULL,              -- electricite(_injection, _sous_compteur), chaleur, cad(_debit, _temperature_*), gaz, eau, eau_chaude, pac_*, mazout, granules, solaire, meteo, rayonnement
    libelle     TEXT NOT NULL,
    unite       TEXT NOT NULL,              -- kWh, m3, degC, kW, l, W/m2, kg, m3/h
    nature      TEXT NOT NULL CHECK (nature IN ('index','intervalle','instantane','livraison')),
    pas_min     INTEGER NOT NULL,           -- pas de temps en minutes : 60 par défaut, 1440 journalier, 43200 mensuel
    source      TEXT NOT NULL,              -- connecteur : M-Bus, wM-Bus, LoRaWAN, DLMS, Modbus, CSV…
    identifiant TEXT,                       -- n° de série, adresse M-Bus, DevEUI…
    fournisseur TEXT,                       -- qui facture ce fluide
    etat        TEXT NOT NULL DEFAULT 'actif' CHECK (etat IN ('actif','a_connecter','inactif')),
    -- installation solaire (fluide 'solaire') : puissance crête, production brute prévue, âge et décote des modules
    puissance_crete_kwc      NUMERIC CHECK (puissance_crete_kwc > 0),
    production_prevue_kwh_an NUMERIC CHECK (production_prevue_kwh_an >= 0),
    mise_en_service          INTEGER,
    degradation_pct_an       NUMERIC CHECK (degradation_pct_an BETWEEN 0 AND 5),
    -- rôle du compteur dans le site et bornes de service (mois inclusifs AAAA-MM)
    niveau        TEXT,                     -- général, sous-compteur, production, livraison, courbe de charge…
    parent_id     TEXT,                     -- compteur de rattachement (sous-compteur, ou courbe fine d'un relevé mensuel)
    service_debut TEXT,
    service_fin   TEXT,
    releve        TEXT                      -- mode de collecte (automatique mensuel, bon de livraison, courbe horaire…)
);

-- Appareil physique (permet de changer un compteur sans casser la série)
CREATE TABLE appareil (
    id            TEXT PRIMARY KEY,
    point_id      TEXT NOT NULL REFERENCES point_mesure(id),
    numero_serie  TEXT,
    date_pose     TIMESTAMPTZ NOT NULL,
    date_depose   TIMESTAMPTZ,
    index_pose    NUMERIC,
    index_depose  NUMERIC
);

-- Déclarations du gestionnaire (vigie/declarations.py) : sourdine justifiée d'une règle, travaux ou vacance datés
-- (règles d'énergie suspendues, jours exclus de la référence), changement (compteur remplacé, consigne ou courbe de
-- chauffe modifiée : la référence ne remonte pas avant). Chaque déclaration est tracée dans l'historique (evenement).
CREATE TABLE declaration (
    id          BIGSERIAL PRIMARY KEY,
    immeuble_id TEXT NOT NULL REFERENCES immeuble(id),
    type        TEXT NOT NULL CHECK (type IN ('sourdine','travaux','vacance','changement')),
    cause       TEXT,                       -- sourdine : règle concernée
    point_id    TEXT,                       -- changement : compteur concerné (NULL = tous ceux de l'immeuble)
    debut       DATE NOT NULL,              -- date d'effet (changement : date du changement)
    fin         DATE,                       -- obligatoire pour sourdine, travaux et vacance
    motif       TEXT NOT NULL,
    auteur      TEXT,
    cree_le     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX declaration_immeuble ON declaration (immeuble_id);

-- ---------- Mesures ----------
CREATE TABLE mesure (
    ts        TIMESTAMPTZ NOT NULL,         -- UTC, convention fin d'intervalle
    point_id  TEXT NOT NULL REFERENCES point_mesure(id),
    valeur    DOUBLE PRECISION NOT NULL,
    qualite   TEXT NOT NULL DEFAULT 'valide' CHECK (qualite IN ('valide','estimee','suspecte')),
    lot_import TEXT,
    PRIMARY KEY (point_id, ts)
);
SELECT create_hypertable('mesure', 'ts');

-- Agrégat horaire continu (consommation par pas, alimente la détection)
CREATE MATERIALIZED VIEW mesure_horaire
WITH (timescaledb.continuous) AS
SELECT point_id, time_bucket('1 hour', ts) AS heure,
       sum(valeur) AS somme, min(valeur) AS mini, max(valeur) AS maxi, count(*) AS nb
FROM mesure
GROUP BY point_id, heure;

-- ---------- Règles et alertes ----------
CREATE TABLE regle (
    id          TEXT PRIMARY KEY,
    portee      TEXT NOT NULL,              -- parc | adresse:<id> | immeuble:<id> | point:<id>
    fluide      TEXT NOT NULL,
    detecteur   TEXT NOT NULL,              -- eau_nuit, chaleur_signature, pac_cop…
    parametres  JSONB NOT NULL,             -- seuils, persistance, pas minimal
    profils     TEXT[],                     -- profils concernés, NULL = tous
    gravite     TEXT NOT NULL,
    consigne    TEXT NOT NULL,
    active      BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE alerte (
    id           TEXT PRIMARY KEY,
    immeuble_id  TEXT NOT NULL REFERENCES immeuble(id),
    point_id     TEXT REFERENCES point_mesure(id),
    cause        TEXT NOT NULL,
    gravite      TEXT NOT NULL,
    debut_derive TIMESTAMPTZ NOT NULL,
    ouverte_le   TIMESTAMPTZ NOT NULL DEFAULT now(),
    cloturee_le  TIMESTAMPTZ,
    confiance    NUMERIC(4,3),
    chiffrage    TEXT CHECK (chiffrage IN ('annuel','mesure')),  -- eau/électricité : annuel ; chauffage/PAC : mesuré
    periode      TEXT,                                           -- libellé de la période chiffrée
    kwh_an       NUMERIC, m3_an NUMERIC, chf_an NUMERIC, co2_t_an NUMERIC,                  -- eau, électricité (= projection)
    kwh_mois     NUMERIC, m3_mois NUMERIC, chf_mois NUMERIC, co2_t_mois NUMERIC,            -- rythme par 30 jours
    kwh_mesure   NUMERIC, m3_mesure NUMERIC, chf_mesure NUMERIC, co2_t_mesure NUMERIC,      -- dérive CONSTATÉE depuis le début
    kwh_proj     NUMERIC, m3_proj NUMERIC, chf_proj NUMERIC, co2_t_proj NUMERIC,            -- projection 12 mois (hypothèse)
    projection   TEXT,                                           -- libellé de l'hypothèse de projection
    heures_mesurees INTEGER,
    score        NUMERIC,
    constat      TEXT, consigne TEXT,
    retour       TEXT CHECK (retour IN ('pertinente','deja_connue','fausse_alerte')),
    gain_mesure_chf_an NUMERIC,
    UNIQUE (immeuble_id, cause, ouverte_le)  -- 1 alerte par cause et par immeuble
);

-- ---------- Gestion (V0.2) : suivi des alertes, réglages, prestataires, bons de travaux ----------
-- Le prototype SQLite stocke les réglages de règle du gestionnaire par détecteur (table regle simplifiée :
-- id = détecteur, colonnes active, profils, seuil, persistance, gravite, delai, metier, consigne).
ALTER TABLE alerte ADD COLUMN statut TEXT NOT NULL DEFAULT 'ouverte' CHECK (statut IN ('ouverte','resolue'));
ALTER TABLE alerte ADD COLUMN derniere_detection TIMESTAMPTZ;
ALTER TABLE alerte ADD COLUMN retour_le TIMESTAMPTZ;
ALTER TABLE alerte ADD COLUMN donnees JSONB;            -- alerte structurée calculée par le moteur

CREATE TABLE parametre (                                 -- tarifs, facteurs CO2, paramètres moteur, messagerie
    cle    TEXT PRIMARY KEY,
    valeur JSONB NOT NULL                                -- jamais de mot de passe ici
);

CREATE TABLE prestataire (
    id        BIGSERIAL PRIMARY KEY,
    nom       TEXT NOT NULL,
    metier    TEXT NOT NULL,                             -- Sanitaire, Chauffagiste, Frigoriste, Concierge, Télérelève…
    contact   TEXT,
    email     TEXT NOT NULL,
    telephone TEXT,
    perimetre TEXT NOT NULL DEFAULT '*',                 -- '*' = tout le parc, sinon codes d'immeubles séparés par des virgules
    actif     BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE bon (
    id             BIGSERIAL PRIMARY KEY,
    numero         TEXT UNIQUE NOT NULL,                 -- BT-AAAA-NNNN
    alerte_id      TEXT NOT NULL REFERENCES alerte(id),
    immeuble_id    TEXT NOT NULL,
    prestataire_id BIGINT REFERENCES prestataire(id),
    statut         TEXT NOT NULL CHECK (statut IN ('brouillon','envoye','en_cours','termine','annule')),
    cree_le        TIMESTAMPTZ NOT NULL DEFAULT now(),
    envoye_le      TIMESTAMPTZ,
    cloture_le     TIMESTAMPTZ,
    destinataire   TEXT,
    objet          TEXT NOT NULL,
    corps          TEXT NOT NULL,
    mode           TEXT NOT NULL CHECK (mode IN ('auto','manuel')),
    journal        JSONB NOT NULL DEFAULT '[]'
);
-- Un seul bon ouvert par alerte
CREATE UNIQUE INDEX bon_ouvert_unique ON bon (alerte_id) WHERE statut IN ('brouillon','envoye','en_cours');
