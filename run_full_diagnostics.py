# run_full_diagnostics.py (Versio 3.0 Local - Täydellinen ja korjattu)
import os
import logging
import time
import json
import re
from collections import defaultdict

from logic import (
    lataa_raamattu, luo_kanoninen_avain, luo_hakusuunnitelma,
    validoi_avainsanat_ai, etsi_mekaanisesti, suodata_semanttisesti,
    pisteyta_ja_jarjestele
)

LOG_FILENAME = 'full_diagnostics_report_v3.0_local.txt'
if os.path.exists(LOG_FILENAME):
    os.remove(LOG_FILENAME)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    datefmt='%H:%M:%S',
    handlers=[
        logging.FileHandler(LOG_FILENAME, encoding='utf-8'),
        logging.StreamHandler()
    ]
)


def log_header(title):
    """Luo ja tulostaa vakio otsikon lokitiedostoon."""
    logging.info("\n" + "=" * 80)
    logging.info(f"--- {title.upper()} ---")
    logging.info("=" * 80)


def onko_sana_hyvaksyttava(sana, sanakirja):
    """
    Tarkistaa, onko sana tai sen osa raamatullinen.
    Sallii moniosaiset termit, jos yksikin osa löytyy.
    Säilytetty alkuperäisestä tiedostosta.
    """
    clean_sana = sana.lower().strip()
    if not clean_sana:
        return False

    osat = clean_sana.split()
    for osa in osat:
        if osa in sanakirja:
            return True
        if len(osa) > 6 and osa.endswith(('n', 'ä', 'a')):
            if osa[:-1] in sanakirja:
                return True
        if len(osa) > 7 and osa.endswith(('ssa', 'ssä')):
            if osa[:-3] in sanakirja:
                return True
        if len(osa) > 7 and osa.endswith(('sta', 'stä')):
            if osa[:-3] in sanakirja:
                return True
    return False


def hae_jae_viitteella(viite_str, book_data_map, book_name_map_by_id):
    """
    Hakee tarkan jakeen tekstin viitteen perusteella.
    Säilytetty alkuperäisestä tiedostosta.
    """
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


def run_diagnostics():
    """Suorittaa koko diagnostiikka-ajon paikallisella mallilla."""
    total_start_time = time.perf_counter()
    log_header("Raamattu-tutkija 3.0 - DIAGNOSTIIKKA (Paikallinen Ajo)")

    logging.info("\n[ALUSTUS] Ladataan Raamattu ja sanakirja...")
    raamattu_resurssit = lataa_raamattu(
        'bible.json', 'bible_dictionary.json'
    )
    if not raamattu_resurssit:
        logging.error("KRIITTINEN: Resurssien lataus epäonnistui.")
        return
    (
        _, _, book_name_map_by_id, book_data_map, _,
        book_name_to_id_map, raamattu_sanakirja
    ) = raamattu_resurssit
    logging.info("Resurssit ladattu onnistuneesti.")

    try:
        with open("syote.txt", "r", encoding="utf-8") as f:
            syote_teksti = f.read().strip()
            pääaihe = syote_teksti.splitlines()[0]
        logging.info("Syötetiedosto 'syote.txt' ladattu onnistuneesti.")
    except (FileNotFoundError, IndexError):
        logging.error("KRIITTINEN: 'syote.txt' ei löytynyt tai on tyhjä.")
        return

    log_header("VAIHE 1: HAKUSUUNNITELMA & AVAINSANOJEN VALIDointi")
    start_time = time.perf_counter()
    logging.info("Lähetetään pyyntö tekoälymallille hakusuunnitelman luomiseksi (tämä voi kestää)...")
    suunnitelma, _ = luo_hakusuunnitelma(pääaihe, syote_teksti)

    if not suunnitelma:
        logging.error("TESTI KESKEYTETTY: Hakusuunnitelman luonti epäonnistui.")
        return
    logging.info(
        f"Hakusuunnitelma luotu onnistuneesti. Aikaa kului: {time.perf_counter() - start_time:.2f} sek."
    )
    logging.info("--- Alkuperäinen hakusuunnitelma ---")
    logging.info(json.dumps(suunnitelma, indent=2, ensure_ascii=False))

    logging.info("\n--- Avainsanojen validointi tekoälyllä ---")
    start_time_val = time.perf_counter()
    kaikki_avainsanat = list(set(
        sana for avainsanalista in suunnitelma["hakukomennot"].values()
        for sana in avainsanalista
    ))
    logging.info(f"Lähetetään {len(kaikki_avainsanat)} avainsanaa tekoälymallille validointiin...")
    hyvaksytyt_sanat_setti = validoi_avainsanat_ai(
        kaikki_avainsanat, lambda usage: None
    )

    puhdistetut_komennot = {}
    for osio, avainsanat in suunnitelma["hakukomennot"].items():
        hyvaksytyt = [s for s in avainsanat if s in hyvaksytyt_sanat_setti]
        poistetut = [s for s in avainsanat if s not in hyvaksytyt_sanat_setti]
        puhdistetut_komennot[osio] = hyvaksytyt
        if poistetut:
            logging.info(
                f"Osio {osio}: Hylättiin epäraamatulliset käsitteet: "
                f"{', '.join(poistetut)}"
            )
    suunnitelma["hakukomennot"] = puhdistetut_komennot
    logging.info(
        f"Avainsanojen validointi valmis. Aikaa kului: "
        f"{time.perf_counter() - start_time_val:.2f} sek."
    )

    log_header("VAIHE 2: JAKEIDEN KERÄYS (ESIHAKU + ÄLYKÄS VALINTA)")
    start_time = time.perf_counter()
    osio_kohtaiset_jakeet = defaultdict(set)
    hakukomennot = suunnitelma["hakukomennot"]
    total_sections = len(hakukomennot)

    for i, (osio_nro, avainsanat) in enumerate(hakukomennot.items()):
        teema_match = re.search(
            r"^{}\.?\s*(.*)".format(re.escape(osio_nro.strip('.'))),
            suunnitelma["vahvistettu_sisallysluettelo"], re.MULTILINE
        )
        teema = teema_match.group(1).strip() if teema_match else ""
        if not teema or not avainsanat:
            continue

        logging.info(
            f"\n  ({i+1}/{total_sections}) Käsitellään osiota {osio_nro}: "
            f"{teema}..."
        )
        kandidaatit = etsi_mekaanisesti(
            avainsanat, book_data_map, book_name_map_by_id
        )
        logging.info(f"    - Mekaaninen haku löysi {len(kandidaatit)} kandidaattijaetta.")

        if kandidaatit:
            logging.info(f"    - Lähetetään {len(kandidaatit)} jaetta tekoälylle semanttiseen suodatukseen...")
            valinnat, _ = suodata_semanttisesti(kandidaatit, teema)
            logging.info(f"    - Tekoäly valitsi {len(valinnat)} relevanttia jaeviitettä.")

            for valinta in valinnat:
                if not isinstance(valinta, dict):
                    continue
                viite_str = valinta.get("viite")
                laajenna = valinta.get("laajenna_kontekstia", False)

                if not viite_str:
                    continue
                jae = hae_jae_viitteella(
                    viite_str, book_data_map, book_name_map_by_id
                )
                if jae:
                    osio_kohtaiset_jakeet[osio_nro].add(jae)
                    if laajenna:
                        match = re.match(r'^(.*?)\s+(\d+):(\d+)', jae)
                        if not match:
                            continue
                        b_name, ch, v_num = match.groups()
                        for j in range(1, 3):
                            seuraava_jae = hae_jae_viitteella(
                                f"{b_name} {ch}:{int(v_num) + j}",
                                book_data_map, book_name_map_by_id
                            )
                            if seuraava_jae:
                                osio_kohtaiset_jakeet[osio_nro].add(
                                    seuraava_jae
                                )
        time.sleep(1.5) # Pieni tauko, ettei käyttöliittymä tunnu täysin jumiutuneelta

    kaikki_jakeet = set().union(*osio_kohtaiset_jakeet.values())
    logging.info(
        f"\nJakeiden keräys valmis. Aikaa kului: "
        f"{time.perf_counter() - start_time:.2f} sekuntia."
    )
    logging.info(f"Kerättyjä uniikkeja jakeita yhteensä: {len(kaikki_jakeet)} kpl.")

    log_header("VAIHE 3: JAKEIDEN JÄRJESTELY JA PISTEYTYS")
    start_time = time.perf_counter()

    def progress_logger(percent, text):
        logging.info(f"  - Edistyminen: {percent}% - {text}")

    logging.info("Käynnistetään jakeiden pisteytys ja järjestely tekoälymallilla (tämä voi kestää kauan)...")
    jae_kartta = pisteyta_ja_jarjestele(
        pääaihe,
        suunnitelma["vahvistettu_sisallysluettelo"],
        {k: list(v) for k, v in osio_kohtaiset_jakeet.items()},
        lambda usage: None,
        progress_callback=progress_logger
    )
    logging.info(
        f"Järjestely valmis. Aikaa kului: "
        f"{time.perf_counter() - start_time:.2f} sekuntia."
    )

    log_header("LOPULLISET TULOKSET")
    total_end_time = time.perf_counter()
    uniikit_jarjestellyt, sijoituksia = set(), 0
    if jae_kartta:
        for data in jae_kartta.values():
            uniikit_jarjestellyt.update(data.get('relevantimmat', []))
            uniikit_jarjestellyt.update(data.get('vahemman_relevantit', []))
            sijoituksia += (len(data.get('relevantimmat', [])) +
                            len(data.get('vahemman_relevantit', [])))

    logging.info(
        f"KOKONAISKESTO: {(total_end_time - total_start_time) / 60:.1f} min."
    )
    logging.info(f"Kerätyt jakeet (uniikit): {len(kaikki_jakeet)} kpl")
    logging.info(
        f"Järjestellyt jakeet (uniikit): {len(uniikit_jarjestellyt)} kpl"
    )
    logging.info(f"Sijoituksia osioihin yhteensä: {sijoituksia} kpl")

    log_header("YKSITYISKOHTAINEN JAEJAOTTELU")
    if jae_kartta:
        sorted_jae_kartta = sorted(
            jae_kartta.items(),
            key=lambda item: [int(p) for p in item[0].strip('.').split('.')]
        )
        for osio, data in sorted_jae_kartta:
            rel, v_rel = data.get('relevantimmat', []), \
                data.get('vahemman_relevantit', [])
            logging.info(
                f"\n--- Osio {osio} (Yhteensä: {len(rel) + len(v_rel)}) ---"
            )
            if not rel and not v_rel:
                logging.info("  - Ei jakeita tähän osioon.")
                continue
            if rel:
                logging.info(f"  --- Relevantimmat ({len(rel)} jaetta) ---")
                for jae in sorted(
                    rel, key=lambda j: luo_kanoninen_avain(j, book_name_to_id_map)
                ):
                    logging.info(f"    - {jae}")
            if v_rel:
                logging.info(
                    f"  --- Vähemmän relevantit ({len(v_rel)} jaetta) ---"
                )
                for jae in sorted(
                    v_rel, key=lambda j: luo_kanoninen_avain(j, book_name_to_id_map)
                ):
                    logging.info(f"    - {jae}")


if __name__ == "__main__":
    run_diagnostics()
    log_header("DIAGNOSTIIKKA VALMIS")