# logic.py (Versio 3.0 Local)
import io
import json
import re
import time
import docx
import PyPDF2
import requests


# --- MALLIASETUKSET ---
FAST_MODEL = "llama3"  # Nopea yleismalli
# Voit vaihtaa tähän myös "turkunlp/poro-34b-instruct", jos haluat laatua nopeuden sijaan
POWERFUL_MODEL = "poro-local" # Itse asennettu, laadukas Suomi-malli
TEOLOGINEN_PERUSOHJE = (
    "Olet teologinen assistentti. Perusta kaikki vastauksesi ja tulkintasi "
    "ainoastaan sinulle annettuihin KR33/38-raamatunjakeisiin ja käyttäjän "
    "materiaaliin. Vältä nojaamasta tiettyihin teologisiin järjestelmiin ja "
    "pyri tulkitsemaan jakeita koko Raamatun kokonaisilmoituksen valossa."
)


def lataa_raamattu(raamattu_path, sanakirja_path):
    """Lataa Raamattu-datan ja sanakirjan paikallisista JSON-tiedostoista."""
    try:
        print(f"Ladataan Raamattu-dataa tiedostosta: {raamattu_path}")
        with open(raamattu_path, 'r', encoding='utf-8') as f:
            bible_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"KRIITTINEN VIRHE Raamattu-datan latauksessa: {e}")
        return None

    try:
        print(f"Ladataan sanakirjaa tiedostosta: {sanakirja_path}")
        with open(sanakirja_path, 'r', encoding='utf-8') as f:
            raamattu_sanakirja = set(json.load(f))
        print(f"Ladattu {len(raamattu_sanakirja)} sanaa Raamattu-sanakirjasta.")
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"KRIITTINEN VIRHE sanakirjan latauksessa: {e}")
        return None

    # Jäsennellään kirjat kuten aiemminkin
    book_map, book_name_map, book_data_map, book_name_to_id_map = {}, {}, {}, {}
    sorted_book_ids = sorted(bible_data.get("book", {}).keys(), key=int)
    for book_id in sorted_book_ids:
        book_content = bible_data["book"][book_id]
        book_data_map[book_id] = book_content
        info = book_content.get("info", {})
        proper_name = info.get("name", f"Kirja {book_id}")
        book_name_map[book_id] = proper_name
        book_name_to_id_map[proper_name] = int(book_id)
        names = ([info.get("name", ""), info.get("shortname", "")] +
                 info.get("abbr", []))
        for name in names:
            if name:
                key = name.lower().replace(".", "").replace(" ", "")
                if key:
                    book_map[key] = (book_id, book_content)
    
    sorted_aliases = sorted(
        list(set(alias for alias in book_map if alias)), key=len, reverse=True
    )
    return (
        bible_data, book_map, book_name_map, book_data_map,
        sorted_aliases, book_name_to_id_map, raamattu_sanakirja
    )


def luo_kanoninen_avain(jae_str, book_name_to_id_map):
    """Luo järjestelyavaimen (kirja, luku, jae) merkkijonosta."""
    match = re.match(r'^(.*?)\s+(\d+):(\d+)', jae_str)
    if not match:
        return (999, 999, 999)
    book_name, chapter, verse = match.groups()
    book_id = book_name_to_id_map.get(book_name.strip(), 999)
    return (book_id, int(chapter), int(verse))


def erota_jaeviite(jae_kokonainen):
    """Erottaa ja palauttaa jaeviitteen tekoälyä varten."""
    try:
        return jae_kokonainen.split(' - ')[0].strip()
    except IndexError:
        return jae_kokonainen


def lue_ladattu_tiedosto(uploaded_file):
    """Lukee käyttäjän lataaman tiedoston sisällön tekstiksi."""
    if not uploaded_file:
        return ""
    try:
        ext = uploaded_file.name.split(".")[-1].lower()
        bytes_io = io.BytesIO(uploaded_file.getvalue())
        if ext == "pdf":
            return "".join(
                p.extract_text() + "\n"
                for p in PyPDF2.PdfReader(bytes_io).pages
            )
        if ext == "docx":
            return "\n".join(
                p.text for p in docx.Document(bytes_io).paragraphs
            )
        if ext == "txt":
            return uploaded_file.getvalue().decode("utf-8", errors="replace")
    except Exception as e:
        return f"VIRHE TIEDOSTON '{uploaded_file.name}' LUKEMISESSA: {e}"
    return ""


def hae_jae_viitteella(viite_str, book_data_map, book_name_map_by_id):
    """Hakee tarkan jakeen tekstin viitteen perusteella."""
    match = re.match(r'^(.*?)\s+(\d+):(\d+)', viite_str.strip())
    if not match:
        return None

    kirja_nimi_str, luku, jae = match.groups()

    # Etsitään oikea kirjan ID nimen perusteella
    kirja_id = None
    for b_id, b_name in book_name_map_by_id.items():
        if b_name.lower() == kirja_nimi_str.lower().strip():
            kirja_id = b_id
            break

    if kirja_id:
        try:
            oikea_nimi = book_name_map_by_id[kirja_id]
            jae_teksti = book_data_map[kirja_id]['chapter'][luku]['verse'][jae]['text']
            return f"{oikea_nimi} {luku}:{jae} - {jae_teksti}"
        except KeyError:
            return None
    return None


def tee_api_kutsu(prompt, model_name, is_json=False, temperature=0.3):
    """
    Tekee API-kutsun paikallisesti pyörivälle Ollama-palvelimelle.
    """
    OLLAMA_URL = "http://127.0.0.1:11434/api/chat"

    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {
            "temperature": temperature
        }
    }
    
    proxies = {
       "http": None,
       "https": None,
    }

    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=120, proxies=proxies)
        response.raise_for_status()

        response_data = response.json()
        content = response_data.get("message", {}).get("content", "")

        return content, None

    except requests.exceptions.RequestException as e:
        error_message = (
            f"API-VIRHE: Yhteys Ollama-palvelimeen ({OLLAMA_URL}) epäonnistui. "
            f"Varmista, että Ollama-sovellus on käynnissä taustalla. Virhe: {e}"
        )
        print(error_message)
        return error_message, None
    except json.JSONDecodeError:
        error_message = (
            f"API-VIRHE: Ollaman vastauksen JSON-jäsennys epäonnistui. "
            f"Vastaus: {response.text}"
        )
        print(error_message)
        return error_message, None


def luo_hakusuunnitelma(pääaihe, syote_teksti):
    """Luo älykkään hakusuunnitelman paikallisella tekoälyllä."""
    prompt = (
        f"{TEOLOGINEN_PERUSOHJE}\n\n"
        "Tehtäväsi on luoda yksityiskohtainen hakusuunnitelma "
        "Raamattu-tutkimusta varten. Analysoi alla oleva käyttäjän syöte ja "
        "noudata ohjeita tarkasti.\n\n"
        f"PÄÄAIHE: {pääaihe}\n\n"
        "KÄYTTÄJÄN SYÖTE:\n---\n{syote_teksti}\n---\n\n"
        "OHJEET:\n"
        "1. **Tarkista ja viimeistele sisällysluettelo.**\n"
        "2. **Luo kohdennetut hakusanat JOKAISELLE osiolle.**\n"
        "3. **TÄRKEÄ SÄÄNTÖ HAKUSANOILLE:** Kun luot avainsanoja, anna "
        "jokaiselle käsitteelle 2-4 keskeistä muotoa, synonyymiä tai "
        "taivutusmuotoa, jotka löytyvät todennäköisesti KR33/38-Raamatusta. "
        "Ryhmittele samaan listaan toisiinsa liittyvät sanat. Esimerkiksi: "
        "`[\"kutsu\", \"kutsua\", \"kutsuttu\"]` tai "
        "`[\"eksytys\", \"eksyttää\", \"harhaoppi\"]`. "
        "Tämä on kriittistä haun onnistumiseksi.\n"
        "4. **Palauta vastaus TARKALLEEN seuraavassa JSON-muodossa:**\n\n"
        '{{\n'
        '  "vahvistettu_sisallysluettelo": "1. Otsikko...",\n'
        '  "hakukomennot": {{\n'
        '    "1.": ["kutsu", "kutsua", "kutsuttu", "viisaus"],\n'
        '    "2.1.": ["ahneus", "ahne", "petos", "pettää"]\n'
        '  }}\n'
        '}}\n'
    )
    final_prompt = prompt.format(pääaihe=pääaihe, syote_teksti=syote_teksti)
    vastaus_str, usage = tee_api_kutsu(
        final_prompt, POWERFUL_MODEL, is_json=True, temperature=0.3
    )
    if not vastaus_str or vastaus_str.startswith("API-VIRHE:"):
        print(f"API-virhe hakusuunnitelman luonnissa: {vastaus_str}")
        return None, usage
    try:
        # KORJAUS: Etsitään ja eristetään JSON-lohko vastauksesta
        start = vastaus_str.find('{')
        end = vastaus_str.rfind('}')
        if start != -1 and end != -1:
            json_str = vastaus_str[start:end+1]
            return json.loads(json_str), usage
        else:
            raise json.JSONDecodeError("JSON-objektia ei löytynyt vastauksesta.", vastaus_str, 0)

    except json.JSONDecodeError:
        print(f"VIRHE: Hakusuunnitelman JSON-jäsennys epäonnistui: {vastaus_str}")
        return None, usage
    
def validoi_avainsanat_ai(avainsanat, paivita_token_laskuri_callback):
    """
    Validoi avainsanat tekoälyn avulla ja palauttaa hyväksytyt sanat.
    """
    prompt = (
        "Olet suomen kielen ja teologian asiantuntija. Alla on lista hakusanoja. "
        "Tehtäväsi on analysoida jokainen sana ja palauttaa sen todennäköisin "
        "raamatullinen perusmuoto tai käsite.\n\n"
        "Säännöt:\n"
        "1. Jos sana on selkeästi raamatullinen (esim. 'opetuslapsi'), "
        "palauta se sellaisenaan.\n"
        "2. Jos sana on taivutettu muoto tai johdannainen (esim. "
        "'opetuslapseus'), palauta sen tärkein raamatullinen kantasana "
        "(esim. 'opetuslapsi').\n"
        "3. Jos sana on moniosainen raamatullinen käsite (esim. 'terve oppi'), "
        "palauta se sellaisenaan.\n"
        "4. Jos sana on täysin epäraamatullinen (esim. 'YWAM', 'sudenkorento'), "
        "palauta sen arvoksi TYHJÄ MERKKIJONO \"\".\n\n"
        "Hakusanat:\n"
        f"{json.dumps(avainsanat, ensure_ascii=False)}\n\n"
        "VASTAUSOHJE: Palauta VAIN JSON-objekti, jossa avaimena on "
        "alkuperäinen hakusana ja arvona on joko raamatullinen perusmuoto tai "
        "tyhjä merkkijono."
    )
    vastaus_str, usage = tee_api_kutsu(
        prompt, FAST_MODEL, is_json=True, temperature=0.0
    )
    paivita_token_laskuri_callback(usage)

    if not vastaus_str or vastaus_str.startswith("API-VIRHE:"):
        print(f"API-virhe avainsanojen validoinnissa: {vastaus_str}")
        return set()  # Palautetaan tyhjä set virhetilanteessa

    try:
        validointi_tulos = json.loads(vastaus_str)
        hyvaksytyt_sanat = {
            alkuperainen_sana
            for alkuperainen_sana, pätivä_muoto in validointi_tulos.items()
            if pätivä_muoto  # Hyväksytään, jos arvo ei ole tyhjä merkkijono
        }
        return hyvaksytyt_sanat
    except json.JSONDecodeError:
        print(f"JSON-jäsennysvirhe avainsanojen validoinnissa: {vastaus_str}")
        return set()

def etsi_mekaanisesti(avainsanat, book_data_map, book_name_map):
    """Etsii avainsanoja koko Raamatusta ja palauttaa osumat."""
    loydetyt_jakeet = set()
    for sana in avainsanat:
        try:
            pattern = re.compile(re.escape(sana), re.IGNORECASE)
        except re.error:
            continue
        for book_id, book_content in book_data_map.items():
            oikea_nimi = book_name_map.get(book_id, "")
            for luku_nro, luku_data in book_content.get("chapter", {}).items():
                for jae_nro, jae_data in luku_data.get("verse", {}).items():
                    if pattern.search(jae_data.get("text", "")):
                        loydetyt_jakeet.add(
                            f"{oikea_nimi} {luku_nro}:{jae_nro} - "
                            f"{jae_data['text']}"
                        )
    return list(loydetyt_jakeet)


def suodata_semanttisesti(kandidaattijakeet, osion_teema):
    """
    Pyytää tekoälyä valitsemaan relevanteimmat jakeet ja ilmoittamaan,
    milloin kontekstia tulisi laajentaa. Palauttaa JSON-vastauksen.
    """
    if not kandidaattijakeet:
        return [], (None, None, "")

    prompt = (
        "Olet teologinen asiantuntija. Tehtäväsi on arvioida alla olevaa "
        "jaelistaa ja valita sieltä ne, jotka liittyvät annettuun teemaan.\n\n"
        f"**Teema:**\n{osion_teema}\n\n"
        "**Kandidaattijakeet:**\n---\n"
        f"{'\n'.join(kandidaattijakeet)}\n"
        "---\n\n"
        "**OHJEET:**\n"
        "1. Käy läpi kaikki kandidaattijakeet.\n"
        "2. Valitse niistä temaattisesti relevantit.\n"
        "3. Aseta `laajenna_kontekstia`-arvoksi `true` **VAIN**, jos uskot "
        "jakeen teologisen ytimen jäävän ymmärtämättä ilman sitä **seuraavia** "
        "jakeita. Muutoin aseta arvoksi `false`.\n"
        "4. Palauta vastauksesi JSON-muotoisena listana objekteja:\n"
        '[{"viite": "Kirjan nimi Luku:Jae", "laajenna_kontekstia": false}]'
    )
    vastaus_str, usage = tee_api_kutsu(
        prompt, FAST_MODEL, is_json=True, temperature=0.1
    )
    if not vastaus_str or vastaus_str.startswith("API-VIRHE:"):
        print(f"API-virhe semanttisessa suodatuksessa: {vastaus_str}")
        return [], (usage, prompt, vastaus_str)

    try:
        response_json = json.loads(vastaus_str)
        valitut_viitteet = []

        # JOUSTAVA KÄSITTELY: Etsitään jaelista riippumatta avaimesta
        if isinstance(response_json, list):
            valitut_viitteet = response_json
        elif isinstance(response_json, dict):
            # Etsitään avain, jonka arvo on lista
            for key, value in response_json.items():
                if isinstance(value, list):
                    valitut_viitteet = value
                    break  # Käytetään ensimmäistä löytynyttä listaa

        if not valitut_viitteet and isinstance(response_json, dict):
             raise json.JSONDecodeError(
                "JSON-objekti ei sisältänyt listaa.", vastaus_str, 0
            )

        return valitut_viitteet, (usage, prompt, vastaus_str)
    except json.JSONDecodeError as e:
        print(f"JSON-jäsennysvirhe suodatuksessa: {e}")
        return [], (usage, prompt, vastaus_str)


def pisteyta_ja_jarjestele(
    aihe, sisallysluettelo, osio_kohtaiset_jakeet,
    paivita_token_laskuri_callback, progress_callback=None
):
    """Pisteyttää ja järjestelee jakeet erissä tehokkaalla Groq-mallilla."""
    final_jae_kartta = {}
    osiot = {
        match.group(1): match.group(3)
        for rivi in sisallysluettelo.split("\n") if rivi.strip() and
        (match := re.match(r"^\s*(\d+(\.\d+)*)\.?\s*(.*)", rivi.strip()))
    }
    total_osiot = len(osio_kohtaiset_jakeet)
    for i, (osio_nro, jakeet) in enumerate(osio_kohtaiset_jakeet.items()):
        if progress_callback:
            progress_callback(
                int(((i + 1) / total_osiot) * 100),
                f"Järjestellään osiota {osio_nro}..."
            )
        osion_teema = osiot.get(osio_nro.strip('.'), "")
        final_jae_kartta[osio_nro] = {
            "relevantimmat": [], "vahemman_relevantit": []
        }
        if not jakeet or not osion_teema:
            continue

        pisteet, jae_viitteet_lista = {}, [erota_jaeviite(j) for j in jakeet]
        BATCH_SIZE = 50
        for j in range(0, len(jae_viitteet_lista), BATCH_SIZE):
            batch = jae_viitteet_lista[j:j + BATCH_SIZE]
            num_batches = (len(jae_viitteet_lista) + BATCH_SIZE - 1) // BATCH_SIZE
            print(
                f"  - Pisteytetään jakeita osiolle {osio_nro}, "
                f"erä {j//BATCH_SIZE + 1}/{num_batches}..."
            )
            prompt = (
                "Olet teologinen asiantuntija. Pisteytä jokainen alla oleva "
                f"Raamatun jae asteikolla 1-10 sen mukaan, kuinka relevantti "
                f"se on seuraavaan teemaan: '{osion_teema}'. Ota huomioon "
                f"myös tutkimuksen pääaihe: '{aihe}'.\n\n"
                "ARVIOITAVAT JAKEET:\n---\n"
                f"{'\\n'.join(batch)}\n"
                "---\n\n"
                "VASTAUSOHJE: Palauta VAIN JSON-objekti, jossa avaimina ovat "
                "jaeviitteet ja arvoina kokonaisluvut 1-10."
            )
            vastaus_str, usage = tee_api_kutsu(
                prompt, POWERFUL_MODEL, is_json=True, temperature=0.1
            )
            paivita_token_laskuri_callback(usage)
            if vastaus_str and not vastaus_str.startswith("API-VIRHE:"):
                try:
                    pisteet.update(json.loads(vastaus_str))
                except json.JSONDecodeError:
                    print(f"JSON-jäsennysvirhe osiolle {osio_nro}")
            time.sleep(1)

        for jae in jakeet:
            piste = int(pisteet.get(erota_jaeviite(jae), 0))
            if piste >= 7:
                final_jae_kartta[osio_nro]["relevantimmat"].append(jae)
            elif 4 <= piste <= 6:
                final_jae_kartta[osio_nro]["vahemman_relevantit"].append(jae)
    return final_jae_kartta