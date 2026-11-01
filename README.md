# TCG Watch

Surveille les sitemaps publics des enseignes françaises et te prévient quand une nouvelle page
**Pokémon**, **One Piece** ou **Cyberpunk TCG** (booster, display, ETB, coffret, deck...) apparaît,
parfois avant qu'elle soit visible dans le menu du site. Une PWA installable affiche la liste.

Tu ouvres la page et tu commandes toi-même : le bot ne passe aucune commande et ne contourne aucune protection.

## Limites à connaître

- La détection repose sur les sitemaps : certaines enseignes les mettent à jour avec du retard, ou ne listent
  pas les précommandes. Ça ne remplace pas la vérification de leurs pages « Nouveautés ».
- Les alertes arrivent via ntfy/Telegram/Discord. Les notifications push propres à la PWA demandent un petit
  serveur en plus ; ce n'est pas inclus dans cette version.
- Le filtrage se fait sur le texte des adresses (URL). Il peut laisser passer un faux positif ou rater un
  produit dont l'adresse ne mentionne ni le jeu ni le type de produit.

## Tester sans internet

`python tools/test_local.py` simule une enseigne et vérifie la détection de bout en bout.
