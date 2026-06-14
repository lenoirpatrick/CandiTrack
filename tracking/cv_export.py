"""Export de l'analyse d'un CV vers des formats standards (issue #44).

À partir du dictionnaire normalisé ``CV.analysis`` (voir
:func:`tracking.coaching._normalize_cv_analysis`), on produit des représentations
structurées selon trois standards de CV/recrutement :

- **JSON Resume** (https://jsonresume.org/schema/) ;
- **Europass** (modèle « SkillsPassport » JSON) ;
- **HR Open Standards** (objet ``Candidate``, conventions camelCase).

Les périodes d'expérience/formation du CV étant du texte libre, elles sont
exposées telles quelles (champ ``period`` / ``description``) plutôt que découpées
en dates structurées. Stdlib uniquement.
"""

EXPORT_LABELS = {
    "json-resume": "JSON Resume",
    "europass": "Europass",
    "hr-open": "HR-Open",
}


def _nonempty(items):
    """Filtre les chaînes vides d'une liste."""
    return [x for x in items if x]


def to_json_resume(cv):
    """Convertit l'analyse en document JSON Resume (schéma v1.0.0)."""
    a = cv.analysis
    coord = a.get("coordonnees", {})
    summary = " ".join(_nonempty([a.get("infos", ""),
                                   "Permis : " + coord["permis"] if coord.get("permis") else ""]))
    return {
        "$schema": "https://raw.githubusercontent.com/jsonresume/resume-schema/v1.0.0/schema.json",
        "basics": {
            "name": cv.label,
            "label": a.get("titre_profil", ""),
            "email": coord.get("email", ""),
            "phone": coord.get("telephone", ""),
            "summary": summary,
            "location": {
                "address": coord.get("adresse", ""),
                "region": a.get("localisation", ""),
            },
        },
        "work": [
            {
                "name": exp.get("entreprise", ""),
                "position": exp.get("poste", ""),
                "location": exp.get("lieu", ""),
                "url": exp.get("lien", ""),
                "period": exp.get("periode", ""),
                "summary": exp.get("description", ""),
            }
            for exp in a.get("experiences", [])
        ],
        "education": [
            {
                "institution": form.get("etablissement", ""),
                "area": form.get("intitule", ""),
                "url": form.get("lien", ""),
                "location": form.get("lieu", ""),
                "period": form.get("periode", ""),
            }
            for form in a.get("formations", [])
        ],
        "skills": [{"name": c} for c in a.get("competences", [])],
        "languages": [{"language": lang} for lang in a.get("langues", [])],
        "interests": [{"name": h} for h in a.get("loisirs", [])],
    }


def to_europass(cv):
    """Convertit l'analyse au modèle Europass « SkillsPassport » (JSON)."""
    a = cv.analysis
    coord = a.get("coordonnees", {})
    identification = {
        "PersonName": {"FirstName": "", "Surname": cv.label},
        "ContactInfo": {},
    }
    contact = identification["ContactInfo"]
    if coord.get("adresse") or a.get("localisation"):
        contact["Address"] = {"Contact": {
            "AddressLine": coord.get("adresse", ""),
            "Municipality": a.get("localisation", ""),
        }}
    if coord.get("email"):
        contact["Email"] = {"Contact": coord["email"]}
    if coord.get("telephone"):
        contact["Telephone"] = [{"Contact": coord["telephone"]}]

    learner = {
        "Identification": identification,
        "Headline": {
            "Type": {"Code": "position", "Label": "Position visée"},
            "Description": {"Label": a.get("titre_profil", "")},
        },
        "WorkExperience": [
            {
                "Period": {"Label": exp.get("periode", "")},
                "Position": {"Label": exp.get("poste", "")},
                "Activities": exp.get("description", ""),
                "Employer": {
                    "Name": exp.get("entreprise", ""),
                    "ContactInfo": {
                        "Address": {"Contact": {"Municipality": exp.get("lieu", "")}},
                        "Website": {"Contact": exp.get("lien", "")},
                    },
                },
            }
            for exp in a.get("experiences", [])
        ],
        "Education": [
            {
                "Period": {"Label": form.get("periode", "")},
                "Title": form.get("intitule", ""),
                "Organisation": {
                    "Name": form.get("etablissement", ""),
                    "ContactInfo": {
                        "Address": {"Contact": {"Municipality": form.get("lieu", "")}},
                        "Website": {"Contact": form.get("lien", "")},
                    },
                },
            }
            for form in a.get("formations", [])
        ],
        "Skills": {
            "Linguistic": {
                "ForeignLanguage": [
                    {"Description": {"Label": lang}} for lang in a.get("langues", [])
                ],
            },
            "Other": [{"Description": {"Label": c}} for c in a.get("competences", [])],
        },
    }
    if coord.get("permis"):
        learner["DrivingLicence"] = [coord["permis"]]
    if a.get("loisirs"):
        learner["Hobbies"] = {"Description": ", ".join(a["loisirs"])}
    if a.get("infos"):
        learner["Achievement"] = [{"Description": a["infos"]}]

    return {
        "SkillsPassport": {
            "DocumentInfo": {"DocumentType": "ECV", "Generator": "CandiTrack"},
            "LearnerInfo": learner,
        }
    }


def to_hr_open(cv):
    """Convertit l'analyse en objet ``Candidate`` HR Open Standards (JSON)."""
    a = cv.analysis
    coord = a.get("coordonnees", {})
    communication = {}
    if coord.get("email"):
        communication["email"] = [{"address": coord["email"]}]
    if coord.get("telephone"):
        communication["phone"] = [{"dialNumber": coord["telephone"]}]
    if coord.get("adresse") or a.get("localisation"):
        communication["address"] = [{
            "line": _nonempty([coord.get("adresse", "")]),
            "cityName": a.get("localisation", ""),
        }]

    candidate = {
        "personName": {"formattedName": cv.label},
        "communication": communication,
        "profiles": [{"summary": a.get("titre_profil", "")}],
        "employmentHistory": [
            {
                "organizationName": exp.get("entreprise", ""),
                "positionTitle": exp.get("poste", ""),
                "locationSummary": exp.get("lieu", ""),
                "organizationUrl": exp.get("lien", ""),
                "validPeriod": {"description": exp.get("periode", "")},
                "description": exp.get("description", ""),
            }
            for exp in a.get("experiences", [])
        ],
        "educationHistory": [
            {
                "institutionName": form.get("etablissement", ""),
                "programName": form.get("intitule", ""),
                "locationSummary": form.get("lieu", ""),
                "institutionUrl": form.get("lien", ""),
                "validPeriod": {"description": form.get("periode", "")},
            }
            for form in a.get("formations", [])
        ],
        "personCompetencies": [{"competencyName": c} for c in a.get("competences", [])],
        "languageCompetencies": [{"languageName": lang} for lang in a.get("langues", [])],
        "interests": list(a.get("loisirs", [])),
    }
    if coord.get("permis"):
        candidate["licenses"] = [{"name": coord["permis"]}]
    if a.get("infos"):
        candidate["additionalInformation"] = a["infos"]

    return {
        "schemaName": "Candidate",
        "schemaVersion": "1.0",
        "candidate": candidate,
    }


EXPORTERS = {
    "json-resume": to_json_resume,
    "europass": to_europass,
    "hr-open": to_hr_open,
}
