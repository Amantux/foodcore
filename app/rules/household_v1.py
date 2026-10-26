"""What a cook means by a bare food word.

A recipe line says "2 cups flour". A USDA import contains 7,793 foods, of which
"flour" legitimately matches arrowroot, carob, millet, potato and barley malt
flour — so the confidence-tiered matcher refuses, correctly, and the whole
feature returns nothing useful. That refusal is right about the DATA and wrong
about the QUESTION: nobody writing "flour" in a recipe means barley malt.

This module is the missing half: a small, curated, cited vocabulary mapping the
bare words cooks actually write to the specific reference food they mean.

**It is an assumption, and it is labelled as one.** Every resolution through
this table carries ``method="inferred"`` and a confidence well below a direct
match, because "flour means wheat flour" is a cultural convention, not a
measurement. A caller that wants no conventions gets none: the table is only
consulted when the matcher has already failed to find a confident answer, so an
explicit "arrowroot flour" still resolves to arrowroot flour and never comes
near this file.

**The convention encoded here is Anglo-American home cooking**, because that is
what the recipe corpus these apps import is written in. "Flour" is wheat;
"sugar" is granulated white; "cream" is heavy; "rice" is raw long-grain white.
Those defaults are wrong in other cuisines and other kitchens, which is why
this is a versioned rule module rather than a constant buried in the resolver —
a household that disagrees can ship a different version, and the version is
recorded in every value's provenance so a stored figure can be traced to the
assumption that produced it.

Every id below was looked up in a real SR Legacy import and the description is
quoted verbatim, so a reviewer can check the claim without running anything. An
id that does not exist in the loaded dataset is skipped silently: datasets
differ by release and by data-type filter, and a missing row must degrade to
"no household default" rather than to an error.
"""
from __future__ import annotations

#: Bumped whenever a mapping changes meaning. Reaches Provenance.version, so a
#: stored conversion can be traced to the assumption that produced it.
VERSION = "household/2026.10.2"

#: Deliberately lower than a direct catalogue match (0.9) and than a derived
#: density (0.8): this is a convention about language, sitting on top of a
#: measured weight. The weight is solid; the identification is a judgement.
CONFIDENCE = 0.6

#: ``source`` must be a member of provenance.SOURCES. These rules are authored
#: here, so the provider is `internal`; the FDC id of the food they point AT
#: still reaches provenance through the resolved food itself.
SOURCE = "internal"

#: bare word -> (FDC id, the description it names, why this one)
#:
#: Keys are lowercase and matched against the already-normalised food text, so
#: "Flour" and "flour" both arrive here as "flour". Plurals that cooks actually
#: write are listed explicitly rather than stemmed, because stemming "oats" to
#: "oat" would collide with "Oil, oat" — a real near-miss found while building
#: this table.
HOUSEHOLD_FOODS: dict[str, tuple[str, str, str]] = {
    # --- baking staples ---
    "flour": ("168894", "Wheat flour, white, all-purpose, enriched, bleached",
              "unqualified flour in a Western recipe is wheat, white, plain"),
    "plain flour": ("168894", "Wheat flour, white, all-purpose, enriched, bleached",
                    "British name for all-purpose"),
    "all-purpose flour": ("168894", "Wheat flour, white, all-purpose, enriched, bleached",
                          "the American name, spelled out"),
    "sugar": ("169655", "Sugars, granulated",
              "white granulated is the default a recipe assumes"),
    "granulated sugar": ("169655", "Sugars, granulated", "named explicitly"),
    "caster sugar": ("169655", "Sugars, granulated",
                     "finer grind of the same thing; weight per cup differs "
                     "slightly but no separate SR row exists"),
    "brown sugar": ("168833", "Sugars, brown", "packed vs loose is a qualifier, not a food"),
    "cornstarch": ("169698", "Cornstarch", "exact"),
    "cornflour": ("169698", "Cornstarch",
                  "British 'cornflour' is American cornstarch, NOT corn flour "
                  "the milled grain — a genuine false friend"),
    "baking powder": ("172804", "Leavening agents, baking powder, double-acting",
                      "double-acting is the domestic default"),
    "baking soda": ("175040", "Leavening agents, baking soda", "exact"),
    "bicarbonate of soda": ("175040", "Leavening agents, baking soda", "British name"),
    "vanilla extract": ("173471", "Vanilla extract", "exact"),
    "oats": ("173904", "Cereals, oats, regular and quick, not fortified, dry",
             "dry, as bought; cooked oats are a different weight entirely"),

    # --- flours and sugars the matcher reaches but cannot name ---
    #
    # Every one of these HAS a published cup weight that the confidence-tiered
    # matcher cannot get to from a cook's word, so the line silently fell back
    # to a hand-written density or to the wrong flour. They are the highest-value
    # entries in the table precisely because the data was already there.
    "whole wheat flour": ("168893", "Wheat flour, whole-grain",
                          "120 g/cup, not plain flour's 125 -- a different grain "
                          "with different hydration. Consumers strip 'whole' "
                          "during canonicalisation, so this is the only route "
                          "to the right row"),
    "wholemeal flour": ("168893", "Wheat flour, whole-grain", "British name"),
    "wholewheat flour": ("168893", "Wheat flour, whole-grain", "one-word spelling"),
    "bread flour": ("168896", "Wheat flour, white, bread, enriched",
                    "137 g/cup against plain flour's 125. The 9.6% gap sits "
                    "INSIDE a scoop tolerance, so answering with plain flour "
                    "looked correct and was not"),
    "strong flour": ("168896", "Wheat flour, white, bread, enriched",
                     "British name for bread flour"),
    "strong white flour": ("168896", "Wheat flour, white, bread, enriched", "British"),
    "powdered sugar": ("169656", "Sugars, powdered",
                       "120 g/cup unsifted against granulated's 200 -- aeration, "
                       "not a qualifier"),
    "icing sugar": ("169656", "Sugars, powdered", "British name"),
    "confectioners sugar": ("169656", "Sugars, powdered", "American, spelled out"),
    "confectioner's sugar": ("169656", "Sugars, powdered", "with the apostrophe"),
    "cornmeal": ("169697", "Cornmeal, whole-grain, yellow",
                 "122 g/cup. Degermed is 157, so the choice matters; whole-grain "
                 "is what 'cornmeal' unqualified means in a recipe"),
    "cream of tartar": ("175041", "Leavening agents, cream of tartar",
                        "3 g/tsp; always measured by spoon, never by cup"),
    "cocoa powder": ("169593", "Cocoa, dry powder, unsweetened",
                     "unsweetened is the baking default; sweetened is a "
                     "different product entirely"),
    "breadcrumbs": ("174928", "Bread, crumbs, dry, grated, plain",
                    "108 g/cup. The PLAIN row, not the seasoned one at 120 -- "
                    "seasoned is a different product and a different weight"),
    "bread crumbs": ("174928", "Bread, crumbs, dry, grated, plain", "spelled as two words"),
    "molasses": ("168820", "Molasses",
                 "337 g/cup. Filed as plain 'Molasses', NOT under 'Syrups' -- "
                 "which is why a description search for it fails"),

    # --- store-cupboard savoury ---
    "garlic powder": ("171325", "Spices, garlic powder",
                      "3.1 g/tsp. Distinct from fresh garlic by an order of "
                      "magnitude, so resolving it to garlic is not a near-miss"),
    "vinegar": ("172237", "Vinegar, distilled",
                "238 g/cup. Unqualified vinegar is distilled white; a named "
                "vinegar resolves on its own merits before reaching here"),
    "white vinegar": ("172237", "Vinegar, distilled", "named"),
    "ketchup": ("168556", "Catsup",
                "240 g/cup. USDA files it under the archaic 'Catsup', so no "
                "search for 'ketchup' can ever find it -- the single clearest "
                "case for this table existing"),
    "tomato ketchup": ("168556", "Catsup", "as written on the bottle"),
    "lentils": ("172420", "Lentils, raw",
                "192 g/cup RAW. Cooked lentils are a different weight; a line "
                "saying 'cooked' carries that word and is handled upstream"),
    "quinoa": ("168874", "Quinoa, uncooked",
               "170 g/cup UNCOOKED. The cooked row (168917) is 185 and is the "
               "one a description search lands on first"),
    "parsley": ("170416", "Parsley, fresh",
                "3.8 g/tbsp, which is how herbs are actually measured"),
    "cream cheese": ("173418", "Cheese, cream",
                     "232 g/cup. Not 'cheese' and not 'cream'; its own food"),

    # --- dairy ---
    "milk": ("171265", "Milk, whole, 3.25% milkfat, with added vitamin D",
             "unqualified milk is whole cow's milk"),
    "whole milk": ("171265", "Milk, whole, 3.25% milkfat, with added vitamin D", "named"),
    "butter": ("173410", "Butter, salted",
               "salted is the default tub; unsalted differs in sodium, not weight"),
    "cream": ("170859", "Cream, fluid, heavy whipping",
              "unqualified cream in cooking is heavy/double"),
    "heavy cream": ("170859", "Cream, fluid, heavy whipping", "named"),
    "double cream": ("170859", "Cream, fluid, heavy whipping", "British name"),
    "sour cream": ("171257", "Cream, sour, cultured", "exact"),
    "yogurt": ("171284", "Yogurt, plain, whole milk", "unqualified yogurt is plain, whole"),
    "yoghurt": ("171284", "Yogurt, plain, whole milk", "British spelling"),
    "parmesan": ("171247", "Cheese, parmesan, grated",
                 "recipes call for it grated, which is how it is measured"),
    "mozzarella": ("170845", "Cheese, mozzarella, whole milk", "whole milk is the default"),
    "cheddar": ("170899", "Cheese, cheddar, sharp, sliced", "the common supermarket block"),

    # --- eggs ---
    "egg": ("171287", "Egg, whole, raw, fresh", "whole and raw unless stated"),
    "eggs": ("171287", "Egg, whole, raw, fresh", "plural as written"),

    # --- fats and liquids ---
    "oil": ("171413", "Oil, olive, salad or cooking",
            "ambiguous in principle; olive is the commonest cooking oil in the "
            "recipe corpus these apps import, and all cooking oils are within "
            "a few percent of each other by density anyway"),
    "olive oil": ("171413", "Oil, olive, salad or cooking", "exact"),
    "vegetable oil": ("172370", "Oil, vegetable, soybean, refined",
                      "what 'vegetable oil' is sold as; NOT 'Oil, oat', which a "
                      "substring search reaches first"),
    "canola oil": ("172336", "Oil, canola", "exact"),
    "water": ("173647", "Beverages, water, tap, drinking", "1 g/ml by definition"),
    "honey": ("169640", "Honey", "exact"),
    "maple syrup": ("169661", "Syrups, maple", "exact"),
    "lemon juice": ("167747", "Lemon juice, raw", "raw, not bottled concentrate"),
    "peanut butter": ("172470", "Peanut butter, smooth style", "smooth is the default"),

    # --- produce, raw unless a recipe says otherwise ---
    "onion": ("170000", "Onions, raw", "raw; a cup chopped and a cup sliced differ "
              "and the qualifier rule handles that separately"),
    "onions": ("170000", "Onions, raw", "plural as written"),
    "garlic": ("169230", "Garlic, raw", "exact"),
    "tomatoes": ("170457", "Tomatoes, red, ripe, raw", "fresh, not canned"),
    "carrots": ("170393", "Carrots, raw", "exact"),
    "potatoes": ("170026", "Potatoes, flesh and skin, raw", "raw, skin on"),
    "celery": ("169988", "Celery, raw", "exact"),

    # --- grains ---
    "rice": ("168877", "Rice, white, long-grain, regular, raw, enriched",
             "RAW is the critical half: a cup of cooked rice weighs a quarter "
             "less, and a recipe measuring rice measures it dry"),
    "salt": ("173468", "Salt, table", "exact"),

    # --- cooked forms, which are genuinely different foods ---
    #
    # NOT redundant with the raw entries above. "cooked rice" is ambiguous in
    # the data for a real reason — it matches rice noodles, wild rice,
    # glutinous and brown parboiled rice — so without a convention the MORE
    # specific phrase refused while the vaguer "rice" resolved, which is
    # backwards from a cook's point of view.
    "cooked rice": ("169753", "Rice, white, long-grain, regular, cooked, enriched",
                    "white long-grain is what 'cooked rice' means unqualified; "
                    "a cup weighs 158 g against 185 g raw, so keeping the "
                    "distinction matters more than the ambiguity"),
    "cooked pasta": ("169751", "Pasta, cooked, enriched", "same reasoning as cooked rice"),
}


def household_source_id(food_text: str) -> str | None:
    """The FDC id a cook's bare word means, or None if this is not one.

    Case- and whitespace-insensitive; no stemming, no fuzzy matching. A word
    either IS one of the conventions above or it is not, because a near-miss
    here silently converts the wrong food — the failure this whole module is
    meant to avoid rather than cause.
    """
    key = " ".join((food_text or "").lower().split())
    entry = HOUSEHOLD_FOODS.get(key)
    return entry[0] if entry else None


def household_note(food_text: str) -> str:
    """Why that food was chosen, for a caller that wants to show its working."""
    key = " ".join((food_text or "").lower().split())
    entry = HOUSEHOLD_FOODS.get(key)
    return f"{key!r} taken as {entry[1]!r}: {entry[2]}" if entry else ""
