# run_full_diagnostics.py (Versio 4.1 - Parannettu lokitus)
import os
import logging
import time
import json
import re
from collections import defaultdict

from logic import (
    lataa_raamattu, luo_kanoninen_avain, luo_hakusuunnitelma,
    etsi_mekaanisesti, suodata_semanttisesti,
    pisteyta_ja_jarjestele, hae_jae_viitteella, tee_api_kutsu
)

# --- LOKITUSMÄÄRITYKSET ---
LOG_FILENAME = 'full_diagnostics_report_v4.0_local.txt'

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

if logger.hasHandlers():
    logger.handlers.clear()

formatter = logging.Formatter(
    '%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)

try:
    file_handler = logging.FileHandler(LOG_FILENAME, encoding='utf-8', mode='w')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
except Exception as e:
    print(f"KRIITTINEN VIRHE: Lokitiedoston luonti epäonnistui: {e}")

stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)
logger.addHandler(stream_handler)


def log_header(title):
    """Luo ja tulostaa vakio otsikon lokitiedostoon."""
    logging.info("\n" + "=" * 80)
    logging.info(f"--- {title.upper()} ---")
    logging.info("=" * 80)


def run_diagnostics():
    """Suorittaa koko diagnostiikka-ajon yksityiskohtaisella lokituksella."""
    total_start_time = time.perf_counter()
    log_header("Raamattu-tutkija 4.0 - DIAGNOSTIIKKA (PAIKALLINEN AJO)")

    # VAIHE 0: KÄYNNISTYSTARKISTUKSET
    log_header("VAIHE 0: KÄYNNISTYSTARKISTUKSET")
    start_phase_time = time.perf_counter()

    required_files = ['bible.json', 'bible_dictionary.json', 'syote.txt']
    files_ok = True
    for filename in required_files:
        if not os.path.exists(filename):
            logging.critical(f"Tiedostoa '{filename}' ei löytynyt. Pysäytetään.")
            files_ok = False
    if not files_ok:
        return

    logging.info("Tarkistetaan yhteys Ollama-palvelimeen...")
    response = tee_api_kutsu("Hei, toimitko?", "llama3")
    if not response or "API-VIRHE" in response:
        logging.critical(
            "Ollama-palvelin ei vastaa. Varmista, että sovellus on käynnissä."
        )
        return
    logging.info("Ollama-palvelin vastaa onnistuneesti.")
    logging.info(
        f"Käynnistystarkistukset valmiit. Kesto: "
        f"{time.perf_counter() - start_phase_time:.2f} sek."
    )

    # VAIHE 1: ALUSTUS
    log_header("VAIHE 1: ALUSTUS")
    start_phase_time = time.perf_counter()
    raamattu_resurssit = lataa_raamattu('bible.json', 'bible_dictionary.json')
    (
    _, _, book_name_map_by_id, book_data_map, _,
    book_name_to_id_map, raamattu_sanakirja
) = raamattu_resurssit
    try:
        with open("syote.txt", "r", encoding="utf-8") as f:
            syote_teksti = f.read().strip()
            pääaihe = syote_teksti.splitlines()[0]
        logging.info("Syötetiedosto 'syote.txt' ladattu.")
    except IndexError:
        logging.critical("'syote.txt' on tyhjä. Pysäytetään.")
        return
    logging.info(
        f"Alustus valmis. Kesto: {time.perf_counter() - start_phase_time:.2f} sek."
    )

    # VAIHE 2: HAKUSUUNNITELMA & AVAINSANOJEN VALIDOINTI
    log_header("VAIHE 2: HAKUSUUNNITELMA & AVAINSANOJEN VALIDOINTI")
    start_phase_time = time.perf_counter()
    
    suunnitelma = luo_hakusuunnitelma(pääaihe, syote_teksti)
    if not suunnitelma:
        logging.critical("Hakusuunnitelman luonti epäonnistui. Pysäytetään.")
        return
        
    logging.info("Hakusuunnitelma luotu onnistuneesti.")
    
    logging.info("Tarkistetaan avainsanat ohjelmallisesti bible_dictionary.json tiedostoa vasten...")
    
    alkuperaiset_komennot = suunnitelma.get("hakukomennot", {})
    puhdistetut_komennot = {}
    
    for osio, avainsanat in alkuperaiset_komennot.items():
        logging.debug(f"Osion {osio} raa'at avainsanat ({len(avainsanat)} kpl): {avainsanat}")
        hyvaksytyt = [sana for sana in avainsanat if sana.lower() in raamattu_sanakirja]
        hylatyt = [sana for sana in avainsanat if sana.lower() not in raamattu_sanakirja]
        
        if hylatyt:
            logging.info(f"Osio {osio}: Hylättiin {len(hylatyt)} sanaa: {', '.join(hylatyt)}")
        
        puhdistetut_komennot[osio] = hyvaksytyt
        logging.info(f"Osio {osio}: Hyväksyttiin {len(hyvaksytyt)} sanaa.")
        logging.debug(f"Hyväksytyt sanat: {hyvaksytyt}")

    logging.info("Avainsanojen tarkistus valmis.")
    logging.debug(
        "Lopulliset hakukomennot tarkistuksen jälkeen:\n%s",
        json.dumps(puhdistetut_komennot, indent=2, ensure_ascii=False)
    )
    logging.info(
        f"Vaihe 2 valmis. Kesto: {time.perf_counter() - start_phase_time:.2f} sek."
    )

    # VAIHE 3: JAKEIDEN KERÄYS
    log_header("VAIHE 3: JAKEIDEN KERÄYS")
    start_phase_time = time.perf_counter()
    osio_kohtaiset_jakeet = defaultdict(list)
    hakukomennot = puhdistetut_komennot
    
    for i, (osio_nro, avainsanat) in enumerate(hakukomennot.items()):
        sisallysluettelo = suunnitelma.get("vahvistettu_sisallysluettelo", "")
        teema_match = re.search(
            r"^{}\.?\s*(.*)".format(re.escape(osio_nro.strip('.'))),
            sisallysluettelo, re.MULTILINE
        )
        teema = teema_match.group(1).strip() if teema_match else ""
        if not teema or not avainsanat:
            logging.warning(
                f"Ohitetaan osio {osio_nro}, "
                "koska teemaa tai avainsanoja ei ole."
            )
            continue

        logging.info(
            f"({i+1}/{len(hakukomennot)}) Etsitään jakeita osiolle '{teema}'...")
        kandidaatit = etsi_mekaanisesti(
            avainsanat, book_data_map, book_name_map_by_id)
        logging.info(f"  - Löytyi {len(kandidaatit)} mekaanista osumaa.")
        
        if kandidaatit:
            logging.debug("--- KAIKKI MEKAANISET OSUMAT ---")
            for jae in sorted(kandidaatit, key=lambda j: luo_kanoninen_avain(j, book_name_to_id_map)):
                 logging.debug(f"  - {jae}")
            logging.debug("-----------------------------")

            # --- UUSI KAKSIVAIHEINEN SUODATUS ---
            logging.info("  - Aloitetaan esikarsinta: valitaan jakeet, joissa vähintään 2 avainsanaa...")
            esikarsitut_kandidaatit = []
            if len(avainsanat) > 1: # Esikarsinta on järkevää vain jos avainsanoja on enemmän kuin yksi
                for jae in kandidaatit:
                    osumalaskuri = 0
                    # Lasketaan kuinka moni uniikki avainsana löytyy jakeesta
                    for sana in set(avainsanat):
                        if re.search(re.escape(sana), jae, re.IGNORECASE):
                            osumalaskuri += 1
                    if osumalaskuri >= 2:
                        esikarsitut_kandidaatit.append(jae)
            else:
                # Jos avainsanoja on vain yksi, ei voida karsia, joten käytetään kaikkia
                esikarsitut_kandidaatit = kandidaatit
            
            logging.info(f"  - Esikarsinnan jälkeen jäljellä {len(esikarsitut_kandidaatit)} jaetta tekoälyanalyysiin.")
            
            if esikarsitut_kandidaatit:
                valinnat = suodata_semanttisesti(esikarsitut_kandidaatit, teema)
                logging.info(f"  - Tekoäly valitsi {len(valinnat)} lopullista jaetta.")
                for valinta in valinnat:
                    if not isinstance(valinta, dict):
                        continue
                    viite_str = valinta.get("viite")
                    if not viite_str:
                        continue
                    jae = hae_jae_viitteella(
                        viite_str, book_data_map, book_name_map_by_id)
                    if jae:
                        osio_kohtaiset_jakeet[osio_nro].append(jae)
    
    logging.info(
        f"Vaihe 3 valmis. Kesto: {time.perf_counter() - start_phase_time:.2f} sek."
    )

    # VAIHE 4: JAKEIDEN JÄRJESTELY JA PISTEYTYS
    log_header("VAIHE 4: JAKEIDEN JÄRJESTELY JA PISTEYTYS")
    start_phase_time = time.perf_counter()

    def progress_logger(percent, text):
        logging.info(f"  - Edistyminen: {percent}% - {text}")

    jae_kartta = pisteyta_ja_jarjestele(
        pääaihe, suunnitelma.get("vahvistettu_sisallysluettelo", ""),
        osio_kohtaiset_jakeet,
        progress_callback=progress_logger
    )
    logging.info(
        f"Vaihe 4 valmis. Kesto: {time.perf_counter() - start_phase_time:.2f} sek.")

    # VAIHE 5: LOPULLISTEN TULOSTEN KOONTI
    log_header("VAIHE 5: LOPULLISTEN TULOSTEN KOONTI")
    total_end_time = time.perf_counter()
    kaikki_keratyt_jakeet = set()
    for jaelista in osio_kohtaiset_jakeet.values():
        kaikki_keratyt_jakeet.update(jaelista)

    logging.info(
        f"KOKONAISKESTO: {(total_end_time - total_start_time) / 60:.1f} min.")
    logging.info(f"Kerätyt jakeet (uniikit): {len(kaikki_keratyt_jakeet)} kpl")

    log_header("YKSITYISKOHTAINEN JAEJAOTTELU")
    if jae_kartta:
        sorted_jae_kartta = sorted(
            jae_kartta.items(),
            key=lambda item: [
                int(p) for p in item[0].split(' ')[0].strip('.').split('.')
                if p.isdigit()]
        )
        for osio, data in sorted_jae_kartta:
            rel = data.get('relevantimmat', [])
            v_rel = data.get('vahemman_relevantit', [])
            logging.info(
                f"\n--- Osio {osio} (Yhteensä: {len(rel) + len(v_rel)}) ---")
            if not rel and not v_rel:
                logging.info("  - Ei jakeita tähän osioon.")
                continue
            if rel:
                logging.info(
                    f"  --- Relevantimmat ({len(rel)} jaetta) ---")
                for jae in sorted(
                    rel, key=lambda j: luo_kanoninen_avain(j, book_name_to_id_map)):
                    logging.info(f"    - {jae}")
            if v_rel:
                logging.info(
                    f"  --- Vähemmän relevantit ({len(v_rel)} jaetta) ---")
                for jae in sorted(
                    v_rel, key=lambda j: luo_kanoninen_avain(j, book_name_to_id_map)):
                    logging.info(f"    - {jae}")

if __name__ == "__main__":
    run_diagnostics()
    log_header("DIAGNOSTIIKKA VALMIS")