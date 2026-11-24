"""Benchmark for embedding search over the demo SENSEI projects.

Usage examples:
    python scripts/embedding_benchmark.py                                  # run all default benchmarks, rebuilds indexes
    python scripts/embedding_benchmark.py --project alcampo --top-k 5      # rebuilds indexes
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from pathlib import Path
from typing import Iterable, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(REPO_ROOT))

from app.embeddings.embedding_build import get_or_build_index
from app.embeddings.manage_embeddings import get_index_path
from app.embeddings.search_content import search_files

DEFAULT_TOP_K = 3


DEFAULT_BENCHMARKS: dict[str, Mapping[str, object]] = {
    "ada_uam": {
        "project_dir": REPO_ROOT / "sensei_projects" / "ada_uam",
        "queries": [
            {
                "query": "configurar servicios digitales",
                "expect": ["acceso_y_configuración_de_servicios_digitales.yaml"],
            },
            {"query": "soporte estudiantes en moodle", "expect": ["acceso_y_soporte_para_estudiantes.yaml"]},
            {"query": "recuperar identificador id uam", "expect": ["asistencia_técnica_y_cuentas.yaml"]},
            {"query": "contacto del cau", "expect": ["consultante_de_servicios_y_asistencia_del_cau.yaml"]},
            {"query": "problemas acceso moodle", "expect": ["estudiante_con_problemas_de_acceso_a_moodle.yaml"]},
            {
                "query": "información para futuros alumnos",
                "expect": ["información_para_estudiantes_y_futuros_alumnos.yaml"],
            },
            {
                "query": "establecer contraseña por primera vez",
                "expect": ["nuevos_estudiantes_y_personal_en_proceso_de_incorporación.yaml"],
            },
            {
                "query": "préstamo de portátiles en la biblioteca",
                "expect": ["préstamos_y_recursos_de_la_biblioteca.yaml"],
            },
            {"query": "contraseña olvidada id-uam", "expect": ["soporte_técnico_y_gestión_de_contraseñas.yaml"]},
            {"query": "proceso de admisión grados", "expect": ["usuarios_nuevos_y_admisiones.yaml"]},
            {
                "query": "día de bienvenida para nuevos estudiantes",
                "expect": [
                    "usuarios_nuevos_y_admisiones.yaml",
                    "información_para_estudiantes_y_futuros_alumnos.yaml",
                ],
            },
            {
                "query": "vpn para servicios universitarios",
                "expect": [
                    "acceso_y_configuración_de_servicios_digitales.yaml",
                    "préstamos_y_recursos_de_la_biblioteca.yaml",
                ],
            },
            {
                "query": "obtener NIA",
                "expect": [
                    "uso_de_plataformas_virtuales.yaml",
                ],
            },
        ],
    },
    "alcampo": {
        "project_dir": REPO_ROOT / "sensei_projects" / "alcampo",
        "queries": [
            {"query": "wine", "expect": ["wine_and_pairing_recommendations.yaml"]},
            {"query": "vino tinto", "expect": ["wine_and_pairing_recommendations.yaml"]},
            {"query": "recipe", "expect": ["recipe_management_and_cooking_support.yaml"]},
            {"query": "recetas", "expect": ["recipe_management_and_cooking_support.yaml"]},
            {"query": "vino", "expect": ["wine_and_pairing_recommendations.yaml"]},
            {"query": "customer service", "expect": ["customer_service_assistance.yaml"]},
            {"query": "servicio al cliente", "expect": ["customer_service_assistance.yaml"]},
            {"query": "contact form", "expect": ["customer_service_assistance.yaml"]},
            {"query": "delivery", "expect": ["delivery_and_subscription_services.yaml"]},
            {"query": "entrega a domicilio", "expect": ["delivery_and_subscription_services.yaml"]},
            {"query": "subscription", "expect": ["delivery_and_subscription_services.yaml"]},
            {"query": "benefits", "expect": ["delivery_and_subscription_services.yaml"]},
            {"query": "dietary", "expect": ["dietary_needs_and_special_products_inquiry.yaml"]},
            {"query": "preferencias alimentarias", "expect": ["dietary_needs_and_special_products_inquiry.yaml"]},
            {"query": "vegetarian", "expect": ["dietary_needs_and_special_products_inquiry.yaml"]},
            {"query": "plant based", "expect": ["dietary_needs_and_special_products_inquiry.yaml"]},
            {"query": "electronics", "expect": ["electronics_and_smart_products_inquiry.yaml"]},
            {"query": "electrónica", "expect": ["electronics_and_smart_products_inquiry.yaml"]},
            {"query": "smart", "expect": ["electronics_and_smart_products_inquiry.yaml"]},
            {"query": "television", "expect": ["electronics_and_smart_products_inquiry.yaml"]},
            {"query": "fruit", "expect": ["fresh_and_organic_product_inquiry.yaml"]},
            {"query": "fruta", "expect": ["fresh_and_organic_product_inquiry.yaml"]},
            {
                "query": "organic",
                "expect": [
                    "fresh_and_organic_product_inquiry.yaml",
                    "fresh_and_organic_products_exploration.yaml",
                    "fresh_produce_and_sustainability_advocate.yaml",
                ],
            },
            {
                "query": "productos ecológicos",
                "expect": [
                    "fresh_and_organic_product_inquiry.yaml",
                    "fresh_and_organic_products_exploration.yaml",
                    "fresh_produce_and_sustainability_advocate.yaml",
                ],
            },
            {"query": "organic snack", "expect": ["fresh_and_organic_products_exploration.yaml"]},
            {"query": "sustainability", "expect": ["fresh_produce_and_sustainability_advocate.yaml"]},
            {"query": "local", "expect": ["fresh_produce_and_sustainability_advocate.yaml"]},
            {"query": "producto local", "expect": ["fresh_produce_and_sustainability_advocate.yaml"]},
            {
                "query": "product",
                "expect": [
                    "general_shopper_and_member_support.yaml",
                    "dietary_needs_and_special_products_inquiry.yaml",
                    "fresh_and_organic_product_inquiry.yaml",
                    "fresh_and_organic_products_exploration.yaml",
                    "pet_products_inquiry.yaml",
                    "product_discovery_and_promotions.yaml",
                    "product_exploration_and_ordering.yaml",
                    "product_inquiry_and_order_placement.yaml",
                ],
            },
            {
                "query": "promotion",
                "expect": [
                    "general_shopper_and_member_support.yaml",
                    "delivery_and_subscription_services.yaml",
                    "product_discovery_and_promotions.yaml",
                    "promotions_and_offers.yaml",
                ],
            },
            {"query": "member", "expect": ["general_shopper_and_member_support.yaml"]},
            {"query": "socio", "expect": ["general_shopper_and_member_support.yaml"]},
            {"query": "online ordering", "expect": ["online_ordering_process.yaml"]},
            {"query": "pedido online", "expect": ["online_ordering_process.yaml"]},
            {"query": "delivery options", "expect": ["online_ordering_process.yaml"]},
            {"query": "payment process", "expect": ["online_ordering_process.yaml"]},
            {"query": "pet products", "expect": ["pet_products_inquiry.yaml"]},
            {"query": "productos para mascotas", "expect": ["pet_products_inquiry.yaml"]},
            {"query": "pet care", "expect": ["pet_products_inquiry.yaml"]},
            {"query": "animal supplies", "expect": ["pet_products_inquiry.yaml"]},
            {"query": "product discovery", "expect": ["product_discovery_and_promotions.yaml"]},
            {"query": "descubrir productos", "expect": ["product_discovery_and_promotions.yaml"]},
            {"query": "special offers", "expect": ["product_discovery_and_promotions.yaml"]},
            {"query": "grocery ordering", "expect": ["product_exploration_and_ordering.yaml"]},
            {"query": "product categories", "expect": ["product_exploration_and_ordering.yaml"]},
            {"query": "fresh food", "expect": ["product_exploration_and_ordering.yaml"]},
            {
                "query": "fresh",
                "expect": [
                    "product_exploration_and_ordering.yaml",
                    "fresh_and_organic_product_inquiry.yaml",
                    "fresh_and_organic_products_exploration.yaml",
                    "fresh_produce_and_sustainability_advocate.yaml",
                ],
            },
            {
                "query": "explore",
                "expect": ["product_exploration_and_ordering.yaml", "fresh_and_organic_products_exploration.yaml"],
            },
            {"query": "product inquiry", "expect": ["product_inquiry_and_order_placement.yaml"]},
            {"query": "order placement", "expect": ["product_inquiry_and_order_placement.yaml"]},
            {"query": "online orders", "expect": ["product_inquiry_and_order_placement.yaml"]},
            {"query": "discounts", "expect": ["promotions_and_offers.yaml", "general_shopper_and_member_support.yaml"]},
            {"query": "special offers", "expect": ["promotions_and_offers.yaml"]},
            {"query": "recipe management", "expect": ["recipe_management_and_cooking_support.yaml"]},
            {"query": "gestión de recetas", "expect": ["recipe_management_and_cooking_support.yaml"]},
            {"query": "meal planning", "expect": ["recipe_management_and_cooking_support.yaml"]},
            {"query": "ingredient management", "expect": ["recipe_management_and_cooking_support.yaml"]},
            {"query": "shopping experience", "expect": ["shopping_experience_and_app_utilization.yaml"]},
            {"query": "experiencia de compra", "expect": ["shopping_experience_and_app_utilization.yaml"]},
            {
                "query": "shopping",
                "expect": ["shopping_experience_and_app_utilization.yaml", "general_shopper_and_member_support.yaml"],
            },
            {"query": "loyalty programs", "expect": ["shopping_experience_and_app_utilization.yaml"]},
            {"query": "app", "expect": ["shopping_experience_and_app_utilization.yaml"]},
            {"query": "wine recommendations", "expect": ["wine_and_pairing_recommendations.yaml"]},
            {"query": "recomendación de vinos", "expect": ["wine_and_pairing_recommendations.yaml"]},
            {"query": "food pairing", "expect": ["wine_and_pairing_recommendations.yaml"]},
            {"query": "occasion", "expect": ["wine_and_pairing_recommendations.yaml"]},
        ],
    },
    "bikeshop": {
        "project_dir": REPO_ROOT / "sensei_projects" / "bikeshop",
        "queries": [
            {
                "query": "neumatico",
                "expect": [
                    "_customer_seeking_information_on_tires_.yaml",
                    "bike_service_and_repair_inquirer",
                    "qa.yml",
                ],
            },
            {
                "query": "tyre",
                "expect": [
                    "_customer_seeking_information_on_tires_.yaml",
                    "bike_service_and_repair_inquirer",
                    "qa.yml",
                ],
            },
            {
                "query": "tire",
                "expect": [
                    "_customer_seeking_information_on_tires_.yaml",
                    "bike_service_and_repair_inquirer",
                    "qa.yml",
                ],
            },
            {
                "query": "opening and closing time of the bikeshop",
                "expect": ["qa.yml", "user_sim_bikesqa.yml", "general_information_and_support_user.yaml"],
            },
            {
                "query": "horario de la tienda de bicicletas",
                "expect": ["qa.yml", "user_sim_bikesqa.yml", "general_information_and_support_user.yaml"],
            },
            {"query": "set an appointment", "expect": ["appointment.yml"]},
            {"query": "pedir cita", "expect": ["appointment.yml"]},
            {"query": "price of new things", "expect": ["qa.yml", "bike_buyer_and_product_information_seeker.yaml"]},
            {
                "query": "precio de bicicletas nuevas",
                "expect": ["qa.yml", "bike_buyer_and_product_information_seeker.yaml"],
            },
            {"query": "most expensive bike", "expect": ["user_sim_bikesqa.yml"]},
            {"query": "doesn't speak the language", "expect": ["language_issue.yaml"]},
            {"query": "no habla el idioma", "expect": ["language_issue.yaml"]},
        ],
    },
}


def _ensure_index(project_dir: Path, verbose: bool, rebuild: bool) -> Path:
    index_path = get_index_path(project_dir)
    if rebuild and index_path.exists():
        if verbose:
            print(f"[benchmark] rebuild requested for {project_dir.name}, removing cached index at {index_path}")
        index_path.unlink()

    if not index_path.exists():
        if verbose:
            print(f"[benchmark] index not found for {project_dir.name}, building it...")
        get_or_build_index(project_dir)
    return index_path


def _compute_metrics(results: Iterable[Mapping[str, object]], expect: list[str] | None, k: int) -> float:
    if not expect:
        return 0.0

    wanted = {name for name in expect}
    dcg = 0.0
    for idx, r in enumerate(results, start=1):
        fname = str(r.get("filename"))
        if fname in wanted:
            if idx <= k:
                dcg += 1.0 / math.log2(idx + 1)
        if idx >= k:
            break
    ideal = sum(1.0 / math.log2(i + 1) for i in range(1, min(len(wanted), k) + 1))
    ndcg = (dcg / ideal) if ideal else 0.0
    return ndcg


def _format_results(project: str, query: str, expect: list[str] | None, results: Iterable[Mapping[str, object]]) -> str:
    lines = [f"project: {project} | query: {query}"]
    if expect:
        lines.append("expected:")
        for exp in expect:
            lines.append(f"- {exp}")
    lines.append("results:")
    for r in results:
        lines.append(f"- filename: {r['filename']}")
        lines.append(f"  score: {float(r['score'])}")
    return "\n".join(lines)


def run_benchmarks(projects: Iterable[str], *, top_k: int | None, verbose: bool, rebuild: bool = True) -> None:
    overall_total = overall_ndcg = 0.0

    for project in projects:
        cfg = DEFAULT_BENCHMARKS.get(project)
        if not cfg:
            print(f"[benchmark] skipped unknown project '{project}'")
            continue

        project_dir: Path = cfg["project_dir"]  # type: ignore[index]
        queries: Iterable[Mapping[str, object]] = cfg["queries"]  # type: ignore[index]

        index_path = _ensure_index(project_dir, verbose, rebuild)

        total = ndcg_sum = 0.0
        effective_k = top_k if top_k is not None else DEFAULT_TOP_K

        for item in queries:
            query = str(item.get("query"))
            output = search_files(query, index_path, file_types="profiles", top_k=effective_k, state=False)
            expect = item.get("expect")
            expect_list = expect if isinstance(expect, list) else None
            ndcg = _compute_metrics(output["results"], expect_list, effective_k)
            total += 1
            ndcg_sum += ndcg
            metrics = f"ndcg@{effective_k}={ndcg:.3f}" if expect else f"ndcg@{effective_k}=NA"
            print(_format_results(project, query, expect_list, output["results"]))
            print(f"metrics: {metrics}\n")

        if total:
            avg_ndcg = ndcg_sum / total
            print(f"[benchmark] {project} totals (queries={int(total)}): ndcg@{effective_k}={avg_ndcg:.3f}\n")
            overall_total += total
            overall_ndcg += ndcg_sum

    if overall_total:
        print(
            f"[benchmark] overall totals (queries={int(overall_total)}): "
            f"ndcg@{effective_k}={overall_ndcg / overall_total:.3f}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a tiny embedding search benchmark")
    parser.add_argument(
        "--project",
        action="append",
        choices=sorted(DEFAULT_BENCHMARKS.keys()),
        help="Project(s) to benchmark; defaults to all",
    )
    parser.add_argument("--top-k", type=int, default=None, help="Override top_k for all queries")
    parser.add_argument("--verbose", action="store_true", help="Print extra info (index building)")
    parser.add_argument("--offline", action="store_true", help="Force HF_HUB_OFFLINE=1 for the run")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.offline:
        os.environ["HF_HUB_OFFLINE"] = "1"
    projects = args.project or sorted(DEFAULT_BENCHMARKS.keys())
    # Always rebuild the embeddings index so benchmarks run on fresh embeddings.
    run_benchmarks(projects, top_k=args.top_k, verbose=args.verbose, rebuild=True)


if __name__ == "__main__":
    main()
