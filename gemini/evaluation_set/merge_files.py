import json

periodic_properties_data = json.load(open("periodic_properties.json", encoding="utf-8"))
d_and_f_block_data = json.load(open("d_and_f_block.json", encoding="utf-8"))
merged_data = periodic_properties_data + d_and_f_block_data
json.dump(merged_data, open("eval_set.json", "w", encoding="utf-8"), indent=2, ensure_ascii=False)