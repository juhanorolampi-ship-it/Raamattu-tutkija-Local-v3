# logic.py (Versio 4.1 Local - Siistitty ilman token-laskentaa)
import io
import json
import re
import time
import logging
import docx
import PyPDF2
import requests
import ast

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(message)s',
                    datefmt='%H:%M:%S')

# --- MALLIASETUKSET (UUSI STRATEGIA) ---
JSON_MODEL = "qwen2.5:14b"      # Nopea ja luotettava JSON-muotoilija
ANALYST_MODEL = "qwen2.5:14b"   # Syvä teologinen analyytikko
FINNISH_MODEL = "poro-local"            # Suomen kielen asiantuntija

TEOLOGINEN_PERUSOHJE = (
    "Olet teologinen assistentti. Perusta kaikki vastauksesi ja tulkintasi "
    "ainoastaan sinulle annettuihin KR33/38-raamatunjakeisiin ja käyttäjän "
    "materiaaliin. Vältä nojaamasta tiettyihin teologisiin järjestelmiin ja "
    "pyri tulkitsemaan jakeita koko Raamatun kokonaisilmoituksen valossa."
)

def _etsi_json_lohk(text):
    """Etsii ja palauttaa ensimmäisen kelvollisen JSON-objektin tai -listan tekstistä."""
    match = re.search(r'```json\s*(\{.*?\}|\[.*?\])\s*```', text, re.DOTALL)
    if match:
        return match.group(1)
    
    match = re.search(r'(\{.*?\}|\[.*?\])', text, re.DOTALL)
    if match:
        return match.group(1)
        
    return None

def lataa_raamattu(raamattu_path, sanakirja_path):
    """Lataa Raamattu-datan ja sanakirjan paikallisista JSON-tiedostoista."""
    try:
        logging.info(f"Ladataan Raamattu-dataa tiedostosta: {raamattu_path}")
        with open(raamattu_path, 'r', encoding='utf-8') as f:
            bible_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logging.error(f"KRIITTINEN VIRHE Raamattu-datan latauksessa: {e}")
        return None
    try:
        logging.info(f"Ladataan sanakirjaa tiedostosta: {sanakirja_path}")
        with open(sanakirja_path, 'r', encoding='utf-8') as f:
            raamattu_sanakirja = set(json.load(f))
        logging.info(
            f"Ladattu {len(raamattu_sanakirja)} sanaa Raamattu-sanakirjasta.")
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logging.error(f"KRIITTINEN VIRHE sanakirjan latauksessa: {e}")
        return None

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
        list(set(alias for alias in book_map if alias)), key=len, reverse=True)
    return (bible_data, book_map, book_name_map, book_data_map,
            sorted_aliases, book_name_to_id_map, raamattu_sanakirja)


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
                for p in PyPDF2.PdfReader(bytes_io).pages)
        if ext == "docx":
            return "\n".join(
                p.text for p in docx.Document(bytes_io).paragraphs)
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


def tee_api_kutsu(prompt, model_name, is_json=False, temperature=0.3, retries=3):
    """
    Tekee API-kutsun Ollamalle ja yrittää uudelleen epäonnistuessa.
    """
    OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": temperature}
    }
    proxies = {"http": None, "https": None}

    for attempt in range(retries):
        try:
            logging.debug(
                f"Lähetetään pyyntö mallille {model_name} "
                f"(yritys {attempt + 1}/{retries})..."
            )
            response = requests.post(
                OLLAMA_URL, json=payload, timeout=900, proxies=proxies)
            response.raise_for_status()
            response_data = response.json()
            content = response_data.get("message", {}).get("content", "")

            if is_json and not ('{' in content or '[' in content):
                logging.warning(
                    f"Vastaus ei sisältänyt JSON-dataa "
                    f"(yritys {attempt + 1}). Yritetään uudelleen."
                )
                logging.debug(f"Hylätty vastaus: {content}")
                continue

            if content:
                logging.debug(
                    f"Saatiin kelvollinen vastaus mallilta {model_name}.")
                return content

            logging.warning(
                f"API-kutsu onnistui, mutta vastaus oli tyhjä "
                f"(yritys {attempt + 1}). Yritetään uudelleen."
            )

        except requests.exceptions.RequestException as e:
            logging.error(f"API-VIRHE (yritys {attempt + 1}): {e}")
        except json.JSONDecodeError:
            logging.error(
                f"API-VIRHE (yritys {attempt + 1}): Vastaus ei ollut "
                f"kelvollista JSON-muotoa. Vastaus: {response.text}"
            )

        if attempt < retries - 1:
            time.sleep(2)

    logging.critical(
        f"API-kutsu mallille {model_name} epäonnistui {retries} yrityksen jälkeen."
    )
    return f"API-VIRHE: Kutsu epäonnistui {retries} kertaa."


def luo_hakusuunnitelma(pääaihe, syote_teksti):
    """
    Luo hakusuunnitelman käyttäen yhtä tehokasta mallia ja erittäin tarkkaa, monivaiheista kehotetta.
    """
    logging.info("Aloitetaan hakusuunnitelman luonti yhdellä mallilla ja tarkalla kehotteella...")
    # ... (funktion alkuosa pysyy samana, kopioi se aiemmasta versiosta) ...
    sisallysluettelo_match = re.search(
        r"SISÄLLYSLUETTELO.*", syote_teksti, re.IGNORECASE | re.DOTALL
    )
    if not sisallysluettelo_match:
        logging.error("Syötteestä ei löytynyt 'SISÄLLYSLUETTELO'-osiota.")
        return None

    kayttajan_sisallysluettelo = sisallysluettelo_match.group(0).strip()
    osiot = re.findall(r"(^\s*(\d+(\.\d+)*\.).*?)(?=\n\s*\d+(\.\d+)*\.|\Z)", 
                         kayttajan_sisallysluettelo, re.MULTILINE | re.DOTALL)

    if not osiot:
        logging.error("Ei pystytty jäsentämään osioita sisällysluettelosta.")
        return None

    kokonais_hakukomennot = {}
    total_osiot = len(osiot)

    for i, (osio_data) in enumerate(osiot):
        osion_teksti = osio_data[0].strip()
        osion_numero = osio_data[1].strip()
        
        logging.info(f"({i+1}/{total_osiot}) Käsitellään osiota: {osion_numero}")

        # UUSI, YKSITYISKOHTAINEN JA PARANNELTU KEHOTE
        prompt = (
            "Olet teologinen asiantuntija. Tehtäväsi on luoda laadukas lista hakusanoja Raamattu-tutkimusta varten.\n\n"
            f"TUTKIMUKSEN PÄÄAIHE: {pääaihe}\n"
            f"KÄSITELTÄVÄ ALAOTSIKKO:\n---\n{osion_teksti}\n---\n\n"
            "TEE SEURAAVAT VAIHEET:\n"
            "1. **Analysoi** alaotsikon syvin teologinen teema.\n"
            "2. **Ideoi** 4-6 keskeistä peruskäsitettä (sekä substantiiveja että verbejä perusmuodossa), jotka liittyvät teemaan.\n"
            "3. **Laajenna** listaasi lisäämällä kullekin peruskäsitteelle 1-2 tärkeää teologista synonyymiä tai rinnakkaiskäsitettä.\n"
            "4. **Rikasta** listaasi lisäämällä sanoille tärkeitä taivutusmuotoja (esim. 'laki', 'lain', 'lakia').\n"
            "5. **Suosi** sanoja, jotka todennäköisesti löytyvät suomalaisesta KR33/38-Raamatusta.\n"
            "6. **Palauta** lopputulos VAIN yhtenä JSON-listana. Älä selitä tai lisää mitään muuta.\n\n"
            'Esimerkki hyvästä vastauksesta teemalle "2.3 Toimintaohjeet harhaoppia vastaan":\n'
            '["harhaoppi", "harhaoppia", "väärä opetus", "eksytys", "eksytystä", "varoitus", "välttää", "karttaa"]'
        )

        vastaus_str = tee_api_kutsu(
            prompt, ANALYST_MODEL, is_json=True, temperature=0.2
        )

        if not vastaus_str or vastaus_str.startswith("API-VIRHE:"):
            logging.error(f"API-virhe osion {osion_numero} käsittelyssä. Ohitetaan.")
            continue
        
        try:
            json_str = _etsi_json_lohk(vastaus_str)
            if not json_str:
                raise ValueError("Kelvollista JSON-listaa ei löytynyt vastauksesta.")
            
            avainsanat = ast.literal_eval(json_str)
            if isinstance(avainsanat, list):
                # Varmistetaan, että kaikki listan alkiot ovat merkkijonoja
                kokonais_hakukomennot[osion_numero] = [str(s) for s in avainsanat]
                logging.debug(f"  - Saadut avainsanat: {[str(s) for s in avainsanat]}")
            else:
                logging.warning(f"Odotettiin listaa osiolle {osion_numero}, mutta saatiin: {type(avainsanat)}")

        except (ValueError, SyntaxError) as e:
            logging.error(f"JSON-jäsennysvirhe osiolle {osion_numero}: {e}")
        
        time.sleep(1)

    suunnitelma = {
        "vahvistettu_sisallysluettelo": kayttajan_sisallysluettelo,
        "hakukomennot": kokonais_hakukomennot
    }
    
    logging.info("Hakusuunnitelman luonti valmis.")
    return suunnitelma


def validoi_avainsanat_ai(avainsanat):
    """Validoi avainsanat käyttäen JSON-erikoismallia."""
    prompt = (
        "Olet suomen kielen ja teologian asiantuntija. Alla on lista hakusanoja. "
        "Tehtäväsi on analysoida jokainen sana ja palauttaa sen todennäköisin "
        "raamatullinen perusmuoto tai käsite.\n\n"
        "Säännöt:\n"
        "1. Jos sana on selkeästi raamatullinen, palauta se sellaisenaan.\n"
        "2. Jos sana on taivutettu muoto, palauta sen tärkein raamatullinen kantasana.\n"
        "3. Jos sana on täysin epäraamatullinen (esim. 'YWAM'), palauta sen arvoksi TYHJÄ MERKKIJONO \"\".\n\n"
        f"Hakusanat:\n{json.dumps(avainsanat, ensure_ascii=False)}\n\n"
        "VASTAUSOHJE: Palauta VAIN JSON-objekti, jossa avaimena on "
        "alkuperäinen hakusana ja arvona on joko raamatullinen perusmuoto tai "
        "tyhjä merkkijono."
    )
    vastaus_str = tee_api_kutsu(
        prompt, JSON_MODEL, is_json=True, temperature=0.0)
    if not vastaus_str or vastaus_str.startswith("API-VIRHE:"):
        logging.error(f"API-virhe avainsanojen validoinnissa: {vastaus_str}")
        return set()
    
    logging.debug(f"Avainsanojen validoinnin raakavastaus: {vastaus_str}")
    
    try:
        json_str = _etsi_json_lohk(vastaus_str)
        if not json_str:
            raise ValueError("JSON-objektia ei löytynyt vastauksesta.")
            
        validointi_tulos = ast.literal_eval(json_str)
        logging.debug(f"Avainsanojen validointitulos: {validointi_tulos}")
        return {s for s, p in validointi_tulos.items() if p}

    except (ValueError, SyntaxError) as e:
        logging.error(
            f"Jäsennysvirhe avainsanojen validoinnissa: {e}", exc_info=True)
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
                            f"{jae_data['text']}")
    return list(loydetyt_jakeet)


def suodata_semanttisesti(kandidaattijakeet, osion_teema):
    """Pyytää analyytikkomallia valitsemaan relevanteimmat jakeet."""
    if not kandidaattijakeet:
        return []
    prompt = (
    "Olet tekoälyavustaja, jonka AINOA tehtävä on suodattaa alla olevaa jaelistaa. Sinun TÄYTYY noudattaa sääntöjä tarkasti.\n\n"
    f"**Teema, jonka perusteella suodatat:**\n{osion_teema}\n\n"
    f"**Jaelista, josta sinun TÄYTYY tehdä valintasi (et saa käyttää muita jakeita):\n**---\n{'\n'.join(kandidaattijakeet)}\n---\n\n"
    "**SÄÄNNÖT:**\n"
    "1. Käy läpi yllä oleva jaelista.\n"
    "2. Valitse listalta VAIN ne jakeet, jotka ovat erittäin relevantteja annettuun teemaan.\n"
    "3. **ÄLÄ KEKSI TAI LISÄÄ UUSIA JAKEITA.** Valintojesi on tultava vain ja ainoastaan annetusta jaelistasta.\n"
    "4. Palauta vastauksesi JSON-muodossa, jossa on 'viite' ja lyhyt 'perustelu' jokaiselle valinnalle.\n\n"
    '[{"viite": "1. Mooseksen kirja 1:1", "perustelu": "Tämä jae liittyy suoraan teemaan X, koska..."}]'
)
    vastaus_str = tee_api_kutsu(
        prompt, ANALYST_MODEL, is_json=True, temperature=0.1)
        
    if not vastaus_str or vastaus_str.startswith("API-VIRHE:"):
        logging.error(f"API-virhe semanttisessa suodatuksessa: {vastaus_str}")
        return []
        
    logging.debug(
        f"Semanttisen suodatuksen raakavastaus "
        f"osiolle '{osion_teema}': {vastaus_str}"
    )
    
    try:
        json_str = _etsi_json_lohk(vastaus_str)
        if not json_str:
             raise ValueError("JSON-listaa ei löytynyt vastauksesta.")
        
        return ast.literal_eval(json_str)

    except (ValueError, SyntaxError) as e:
        logging.error(f"JSON-jäsennysvirhe suodatuksessa: {e}", exc_info=True)
        return []


def pisteyta_ja_jarjestele(
    aihe, sisallysluettelo, osio_kohtaiset_jakeet, progress_callback=None
):
    """Pisteyttää ja järjestelee jakeet käyttäen analyytikkomallia."""
    final_jae_kartta = {}
    osiot = {
        m.group(1): m.group(3) for r in sisallysluettelo.split("\n")
        if r.strip() and
        (m := re.match(r"^\s*(\d+(\.\d+)*)\.?\s*(.*)", r.strip()))
    }
    total_osiot = len(osio_kohtaiset_jakeet)
    
    for i, (osio_nro, jakeet) in enumerate(osio_kohtaiset_jakeet.items()):
        if progress_callback:
            progress_callback(
                int(((i + 1) / total_osiot) * 100),
                f"Järjestellään osiota {osio_nro}...")
        osion_teema = osiot.get(osio_nro.strip('.'), "")
        final_jae_kartta[osio_nro] = {
            "relevantimmat": [], "vahemman_relevantit": []}
        if not jakeet or not osion_teema:
            continue
            
        pisteet, jae_viitteet_lista = {}, [erota_jaeviite(j) for j in jakeet]
        BATCH_SIZE = 50
        
        for j in range(0, len(jae_viitteet_lista), BATCH_SIZE):
            batch = jae_viitteet_lista[j:j + BATCH_SIZE]
            logging.debug(
                f"Pisteytetään jakeita osiolle {osio_nro}, "
                f"erä {j//BATCH_SIZE + 1}...")
            prompt = (
                "Olet teologinen asiantuntija. Pisteytä jokainen alla oleva "
                f"Raamatun jae asteikolla 1-10 sen mukaan, kuinka relevantti "
                f"se on seuraavaan teemaan: '{osion_teema}'. Ota huomioon "
                f"myös tutkimuksen pääaihe: '{aihe}'.\n\n"
                f"ARVIOITAVAT JAKEET:\n---\n{'\\n'.join(batch)}\n---\n\n"
                "VASTAUSOHJE: Palauta VAIN JSON-objekti, jossa avaimina ovat "
                "jaeviitteet ja arvoina kokonaisluvut 1-10. ÄLÄ SELITÄ VASTAUSTASI."
            )
            vastaus_str = tee_api_kutsu(
                prompt, ANALYST_MODEL, is_json=True, temperature=0.1)
            
            if vastaus_str and not vastaus_str.startswith("API-VIRHE:"):
                logging.debug(f"Pisteytyksen raakavastaus: {vastaus_str}")
                try:
                    json_str = _etsi_json_lohk(vastaus_str)
                    if not json_str:
                        raise ValueError("JSON-objektia ei löytynyt vastauksesta.")
                    
                    data = ast.literal_eval(json_str)
                    if isinstance(data, list):
                        for item in data:
                            pisteet.update(item)
                    elif isinstance(data, dict):
                        pisteet.update(data)

                except (ValueError, SyntaxError) as e:
                    logging.error(
                        f"JSON-jäsennysvirhe osiolle {osio_nro}: {e}",
                        exc_info=True)
            time.sleep(1)
            
        for jae in jakeet:
            piste = int(pisteet.get(erota_jaeviite(jae), 0))
            if piste >= 7:
                final_jae_kartta[osio_nro]["relevantimmat"].append(jae)
            elif 4 <= piste <= 6:
                final_jae_kartta[osio_nro]["vahemman_relevantit"].append(jae)
                
    return final_jae_kartta