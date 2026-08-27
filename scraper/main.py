from load import insert_raw_panel

panel = {
    "title": "Jinko Tiger Neo 505W Black",
    "price_text": "419,00 zł",
    "power_text": "505 W",
    "efficiency_text": "21.3 %",
    "bifaciality_text": "80 %",
    "source_url": "https://example.com",
}

insert_raw_panel(panel)

print("Panel zapisany.")