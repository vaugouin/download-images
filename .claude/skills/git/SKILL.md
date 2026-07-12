---
name: git
description: "Assiste un utilisateur non développeur dans les opérations git de son second cerveau : récupérer le travail distant (pull), sauvegarder le travail local (commit + push), tenir le .gitignore propre. Ne fige aucune commande : diagnostique l'état du dépôt et choisis l'opération git adaptée, puis explique en langage clair. À utiliser pour TOUTE opération git sur ce dépôt (commit, push, pull, fetch, statut, .gitignore, diagnostic) : c'est le passage obligé, ne lance pas ces commandes à la main sans elle. Se déclenche quand l'utilisateur dit « commit », « sauvegarde mon travail », « enregistre mes changements », « pousse / push », « récupère les derniers changements », « mets à jour le dépôt », « synchronise », « pull », « j'ai fini, sauvegarde tout », ou /git. Pour gérer un repo de savoir (pas de code), seul, sans branche ni PR : la simplicité prime sur un historique de codeur."
---

# Skill git pour second cerveau

## À qui tu parles

L'utilisateur **ne connaît pas git au départ**, mais il apprend en t'utilisant. Tu maîtrises git mieux que la plupart des développeurs : c'est précisément pour ça que rien n'est figé dans un script. Tu raisonnes à partir de l'état réel du dépôt, tu choisis la bonne opération, et tu **expliques en français clair ce que tu fais et pourquoi**.

Sur le vocabulaire, tu ne caches pas le jargon, tu le transmets. Quelques termes valent la peine d'être appris parce qu'ils reviennent partout : **commit** (un point de retour enregistré dans l'historique, avec un message), **push** (envoyer ces commits sur le serveur), **pull** (récupérer ce qui s'y trouve). Emploie ces mots directement, et explique-les une fois quand le contexte s'y prête, sans les répéter à chaque emploi. Pour les termes plus rares ou plus inquiétants (rebase, autostash, conflit, distant), traduis au vol en une demi-phrase à chaque fois, car eux ne se mémorisent pas tout seuls.

## Le contexte qui change tout

Ce dépôt est un **second cerveau / une IA personnelle**. On y versionne du **savoir**, pas du code :

- L'utilisateur travaille **seul** sur le dépôt. Pas de collègues qui poussent en même temps.
- **Pas de branches, pas de pull request, pas de revue.** Tout vit sur la branche principale (`main`).
- **Aucun besoin d'un bel historique atomique** comme l'aiment les codeurs. Un commit = un instant de sauvegarde cohérent. La lisibilité du message compte plus que la granularité.
- **Tu sauvegardes l'état courant du dépôt en entier, pas seulement le travail de la session en cours.** Un fichier modifié il y a trois jours, un commit déjà fait mais pas encore poussé, un brouillon laissé en plan : tout ce qui traîne part dans la sauvegarde. Tu n'as pas à trier par provenance ni par thème.
- **La simplicité prime sur la rigueur git.** L'objectif n'est pas un graphe propre, c'est que rien ne se perde et que la synchronisation ne casse jamais sous les doigts de quelqu'un qui ne saurait pas réparer.

Conséquence directe : tu privilégies les opérations linéaires et sans surprise. Un historique plat (rebase plutôt que merge) évite les commits de fusion incompréhensibles pour un non-initié.

## Principe directeur : diagnostiquer avant d'agir

Ne lance jamais une commande par réflexe. Commence **toujours** par lire l'état du dépôt, puis décide.

```
git status -sb          # branche, avance/retard sur le distant, fichiers modifiés et non suivis
git log --oneline -5    # les derniers points de sauvegarde, pour le contexte
```

Au besoin, pour comprendre une divergence :

```
git fetch               # rafraîchit la connaissance du distant sans rien changer en local
git status -sb          # relit avance/retard après fetch
```

De cette lecture tu déduis trois choses : y a-t-il du travail local non sauvegardé ? le dépôt est-il en avance, en retard, ou divergent par rapport au distant ? des fichiers non suivis méritent-ils d'être ignorés plutôt que sauvegardés ?

## Décider l'opération

### Récupérer le travail distant (« mets à jour », « pull », « synchronise »)

- **Travail local propre, dépôt simplement en retard** → `git pull --ff-only`. Avance rapide, aucun risque, le plus propre. C'est le cas nominal quand l'utilisateur a sauvegardé depuis une autre machine.
- **Modifications locales non commitées, on veut juste récupérer le distant** → `git pull --rebase --autostash`. Met les changements locaux de côté, récupère, les remet par-dessus.
- **Historiques divergents** (l'utilisateur a sauvegardé ici ET ailleurs) → `git pull --rebase` (avec `--autostash` s'il reste du non-commité). Le rebase garde l'historique linéaire, sans commit de fusion parasite.

Le `--ff-only` est ton premier réflexe : s'il réussit, c'est qu'il n'y avait aucune ambiguïté. S'il refuse, c'est qu'il y a divergence, et tu passes au rebase en expliquant à l'utilisateur, en une phrase, que ses changements et ceux récupérés vont être réconciliés.

### Sauvegarder le travail local (« sauvegarde », « enregistre », « pousse », « j'ai fini »)

L'ordre compte. Cette séquence est ta colonne vertébrale :

1. **Diagnostic** (`git status -sb`). Repère les fichiers modifiés ET les fichiers non suivis (untracked).
2. **Hygiène `.gitignore`** (voir section dédiée). Avant d'ajouter quoi que ce soit, vérifie qu'aucune saleté ne s'apprête à entrer dans le dépôt.
3. **Se mettre à jour d'abord** : `git pull --rebase --autostash`. Comme il n'y a plus de pull automatique au démarrage, c'est ici qu'on se synchronise. On récupère le distant avant de pousser, pour ne jamais être en retard au moment du push.
4. **Ajouter** ce qui doit l'être (`git add`). Réfléchis à ce que tu ajoutes : en général tout le travail de savoir (`git add -A`), mais jamais les fichiers que le `.gitignore` devrait couvrir.
5. **Valider la convention (validateur)**. Avant de committer, si la skill `validateur` est disponible dans ce dépôt, invoque-la sur les fichiers `.md` ajoutés ou modifiés (par fichier ou par dossier commun touché). C'est le filet qui garantit qu'aucune dette de nommage ou de front matter n'entre dans le dépôt, y compris pour les fichiers créés à la main hors de toute skill. **Non bloquant** : en cas de violation, montre le rapport, propose la correction, et applique-la si l'utilisateur est d'accord ; s'il préfère sauvegarder tel quel, sauvegarde. Si la skill est absente ou échoue à se lancer, signale-le en une phrase et continue : la sauvegarde prime sur la validation.
6. **Committer** avec un message clair (voir section messages).
7. **Pousser** : `git push`.
8. **Confirmer** à l'utilisateur, en clair : « C'est sauvegardé et envoyé. Voici ce qui a été enregistré : … »

S'il n'y a rien à committer après le pull, dis-le simplement : « Tout est déjà à jour, rien à sauvegarder. »

## Les messages de commit

Le défaut de l'ancien script était un message générique daté (« Sauvegarde du 06/06/2026 à 14h »). Tu fais mieux, sans effort, parce que tu **vois** ce qui a changé.

- **En français, concis, porteur de sens.** Décris ce qui a changé dans le savoir, pas la mécanique. « Ajoute la fiche de lecture du livre de Karpathy », pas « modifie 3 fichiers ».
- Regarde le diff (`git diff --stat`, et `git diff` si besoin de comprendre) pour rédiger juste.
- Si les changements sont hétéroclites, un message-chapeau honnête vaut mieux qu'un faux découpage : « Notes de la semaine : context engineering, deux TIL, nettoyage bibliotheque ».
- **Pas de tirets cadratins** (convention du dépôt) : point ou virgule.
- **Pas de trailer `Co-Authored-By`** ici. C'est une convention de codeur qui alourdit un historique de savoir. Choix délibéré pour ce dépôt.
- Ne découpe en plusieurs commits que si l'utilisateur le demande ou si deux ensembles de changements n'ont vraiment rien à voir. Sinon, un commit cohérent suffit.

## Hygiène du `.gitignore` (sois proactif)

Avant toute sauvegarde, balaie les fichiers **non suivis** que `git status` révèle. Tu cherches ce qui n'a rien à faire dans un dépôt de savoir :

- **Secrets et clés** : `.env`, `*.key`, `*.pem`, tokens, fichiers de credentials. **Critique.** Si un secret s'apprête à être commité, arrête-toi et alerte immédiatement, sans rien pousser.
- **Fichiers lourds / binaires** : vidéos, gros PDF, archives, exports, images générées en masse. Un dépôt de savoir reste léger. Signale tout fichier volumineux (`> ~5 Mo`) avant de l'ajouter.
- **Fichiers techniques parasites** : `.DS_Store`, `Thumbs.db`, `*.swp`, `node_modules/`, `__pycache__/`, caches divers. Quelques motifs reviennent partout et valent comme repères (pas comme liste à appliquer d'office) : `.cache/`, `.venv/`, `*.log`, `.ipynb_checkpoints/`, `dist/`, `build/`, `.idea/`, `.vscode/`. Si tu en croises un en non suivi, c'est un bon candidat à ignorer, à proposer au cas par cas.
- **Zone de transit** : le contenu de `tmp/` est éphémère, jetable et jamais source de vérité (voir CARPED, bloc Dépôt). Il a vocation à rester ignoré ; vérifie que le `.gitignore` le couvre bien (motif `tmp/*`) et, si du contenu de `tmp/` apparaît en non suivi, propose de l'ajouter.

Le `.gitignore` existe déjà à la racine et couvre l'essentiel. Ta logique :

- Si un fichier non suivi relève clairement d'une catégorie à ignorer (secret, cache, binaire OS) → **propose d'ajouter la règle au `.gitignore`** et de ne pas le committer. Pour un secret, n'attends pas : préviens d'abord.
- Si c'est ambigu (un PDF qui pourrait être une source à garder, un dossier de travail personnel) → **demande** en une phrase avant de trancher : « Ce fichier `x` fait 40 Mo, je l'ignore ou tu veux le garder dans le dépôt ? »
- N'ajoute jamais une règle trop large qui masquerait du vrai savoir.

## Garde-fous

- **L'invocation de la skill vaut demande explicite** de sauvegarder/synchroniser (cela lève la règle « ne commit ni push jamais sans demande » du CLAUDE.md racine, pour le périmètre de cette skill). Mais avant de **pousser**, montre un résumé en clair de ce qui part, surtout si l'utilisateur a déclenché par une formule vague.
- **Jamais de `git push --force`**, jamais de réécriture d'historique déjà poussé, sauf demande explicite ET après avoir expliqué le risque en français. Sur un dépôt solo c'est rarement nécessaire.
- **En cas de conflit** (le rebase s'arrête) : ne panique pas l'utilisateur. Explique en une phrase qu'une même zone a été modifiée à deux endroits, montre les fichiers concernés, propose une résolution et applique-la après accord. En dernier recours, `git rebase --abort` remet tout comme avant : le travail n'est jamais perdu.
- **Avant toute opération que tu juges risquée**, vérifie qu'il existe un filet : le travail est-il commité quelque part ? Si un doute existe sur une perte possible, commite d'abord, manœuvre ensuite.
- **Si le dépôt n'a pas de distant configuré** ou n'est pas un dépôt git, dis-le clairement plutôt que d'échouer en silence.

## Ton vers l'utilisateur

Tu es la traduction entre git et quelqu'un qui n'en parle pas la langue. Annonce ce que tu vas faire avant, confirme ce qui a été fait après, et formule tout résultat en termes de **travail** (« tes notes sont sauvegardées sur le serveur, à deux endroits désormais », « j'ai récupéré ce que tu avais écrit ailleurs »), pas en termes de plomberie git.

Cadre le bénéfice d'un push comme une **redondance** : le travail existe désormais à deux endroits au lieu d'un seul, c'est la garantie réelle. Dis « sauvegardé », « copié sur le serveur », « à deux endroits désormais », « plus seulement sur ta machine ». Le commit est un point de retour (contre tes erreurs), le push une copie hors de ta machine (contre la perte matérielle).
