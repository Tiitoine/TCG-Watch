# TCG Watch

Surveille les sitemaps publics des enseignes françaises et te prévient quand une nouvelle page
**Pokémon**, **One Piece** ou **Cyberpunk TCG** (booster, display, ETB, coffret, deck...) apparaît,
parfois avant qu'elle soit visible dans le menu du site. Une PWA installable affiche la liste.

Tu ouvres la page et tu commandes toi-même : le bot ne passe aucune commande et ne contourne aucune protection.

## Mise en place (environ 15 minutes)

1. **Crée un dépôt public** sur github.com (par exemple `tcg-watch`) et envoie-y tout le contenu de ce dossier
   (bouton *Add file > Upload files*, y compris le dossier `.github`).
2. **Active la PWA** : *Settings > Pages > Build and deployment* : Source = *Deploy from a branch*,
   branche `main`, dossier `/docs`. L'adresse est du type `https://TON-PSEUDO.github.io/tcg-watch/`.
3. **Teste les enseignes** : onglet *Actions > Vérifier les enseignes > Run workflow*.
   Le journal indique, enseigne par enseigne, si les sitemaps sont lisibles depuis GitHub (OK / KO).
4. **Choisis ton canal d'alerte** (*Settings > Secrets and variables > Actions*) :
   - **ntfy (le plus simple)** : installe l'app *ntfy* (iPhone/Android), abonne-toi à un nom de sujet
     long et impossible à deviner (ex. `tcg-antoine-x7k29q`), puis crée le secret `NTFY_TOPIC` avec ce nom.
   - Telegram : secrets `TELEGRAM_BOT_TOKEN` et `TELEGRAM_CHAT_ID`.
   - Discord : secret `DISCORD_WEBHOOK`.
   - Optionnel : variable (onglet *Variables*) `PWA_URL` = l'adresse de ta PWA, pour que l'alerte l'ouvre.
5. **Lance une première fois** *Actions > TCG Watch > Run workflow*. Ce premier passage sert de référence
   (aucune alerte) ; ensuite, il tourne tout seul toutes les 15 minutes.
6. **Installe la PWA** : ouvre l'adresse sur ton téléphone, puis *Partager > Sur l'écran d'accueil* (iPhone)
   ou *Installer l'application* (Android).

## Ajuster

- `config.json` : liste des enseignes (`sites`) et mots-clés (`rules`). Pour ajouter un jeu (Lorcana,
  Yu-Gi-Oh!...), ajoute une ligne dans `games`. Pour une enseigne, ajoute `{ "id", "name", "base" }`.
- Une enseigne marquée KO au test bloque probablement les adresses de GitHub : retire-la, ou fais tourner
  le script sur ton propre PC (`python detector.py`).

## Limites à connaître

- La détection repose sur les sitemaps : certaines enseignes les mettent à jour avec du retard, ou ne listent
  pas les précommandes. Ça ne remplace pas la vérification de leurs pages « Nouveautés ».
- Les alertes arrivent via ntfy/Telegram/Discord. Les notifications push propres à la PWA demandent un petit
  serveur en plus ; ce n'est pas inclus dans cette version.
- Le filtrage se fait sur le texte des adresses (URL). Il peut laisser passer un faux positif ou rater un
  produit dont l'adresse ne mentionne ni le jeu ni le type de produit.

## Tester sans internet

`python tools/test_local.py` simule une enseigne et vérifie la détection de bout en bout.
