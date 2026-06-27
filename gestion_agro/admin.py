from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.db.models import Sum
from .models import AlerteSecuriteRoutiere
from .models import ProduitAgricole, Transporteur, ZoneProduction, Marche,Reservation, Commercant, Producteur, Livraison, Notification,FluxProduit,Litige


admin.site.register(ZoneProduction)
admin.site.register(Marche)
admin.site.site_header = "SANI-AGRO : Pilotage Mali"

@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('destinataire', 'message', 'date_creation', 'lu')
    list_filter = ('lu', 'date_creation')

@admin.register(ProduitAgricole)
class ProduitAgricoleAdmin(admin.ModelAdmin):
    # On ajoute 'est_promotion' et 'zone_origine' pour plus de clarté
    list_display = ('apercu_image', 'nom', 'prix_unitaire', 'quantite_disponible', 'producteur', 'zone_origine', 'est_promotion')
    
    # On permet de changer le prix ou la promo directement sans ouvrir le produit
    list_editable = ('prix_unitaire', 'quantite_disponible', 'est_promotion')
    
    # On ajoute des filtres sur le côté droit
    list_filter = ('zone_origine', 'est_promotion', 'producteur')
    
    # On permet de chercher un produit par son nom ou son producteur
    search_fields = ('nom', 'producteur__nom_complet', 'zone_origine')

    def apercu_image(self, obj):
        if obj.image:
            return format_html('<img src="{}" style="width: 50px; height: 50px; border-radius: 8px; object-fit: cover;" />', obj.image.url)
        return "Pas de photo"
    apercu_image.short_description = "Photo"

@admin.register(Commercant)
class CommercantAdmin(admin.ModelAdmin):
    list_display = ('nom', 'prenom', 'telephone', 'ville_marche', 'user')

@admin.register(Producteur)
class ProducteurAdmin(admin.ModelAdmin):
    list_display = ('nom_complet', 'village', 'telephone', 'user')
    search_fields = ('nom_complet', 'village')

@admin.register(Transporteur)
class TransporteurAdmin(admin.ModelAdmin):
    list_display = ('nom', 'vehicule', 'plaque_immatriculation', 'disponible', 'user')
    list_filter = ('disponible', 'vehicule')
    list_editable = ('disponible',)
    search_fields = ('nom', 'plaque_immatriculation')

@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    # On ajoute 'statut_caution' et 'confirmation_producteur' dans list_display 
    # pour pouvoir les mettre dans list_editable
    list_display = (
        'id', 'commercant', 'produit', 'quantite_voulue', 
        'prix_total', 'statut_caution', 'confirmation_producteur', 'statut_final'
    )
    # Les champs que tu peux modifier en un clic
    list_editable = ('statut_caution', 'confirmation_producteur')
    list_filter = ('statut_caution', 'confirmation_producteur')

    def statut_final(self, obj):
        if obj.statut_caution == 'PAYE' and obj.confirmation_producteur:
            return mark_safe('<b style="color:green;">✅ VALIDÉE</b>')
        return mark_safe('<b style="color:orange;">⏳ EN COURS</b>')
    statut_final.short_description = "État Global"
    def changelist_view(self, request, extra_context=None):
        from django.db.models import Sum, F
        
        # 1. On prépare les données pour ton HTML
        extra_context = extra_context or {}

        # 2. On calcule le Volume (tonnage)
        # On divise par 1000 si tes données sont en KG pour afficher des "Tonnes"
        volume_kg = Reservation.objects.aggregate(total=Sum('quantite_voulue'))['total'] or 0
        extra_context['tonnage'] = volume_kg / 1000  

        # 3. On calcule la Caisse (total_cautions)
        extra_context['total_cautions'] = Reservation.objects.filter(
            statut_caution='PAYE'
        ).aggregate(total=Sum('caution_20'))['total'] or 0

        # 4. On calcule la Valeur Marchande (ca_total)
        # Quantité * Prix unitaire
        extra_context['ca_total'] = Reservation.objects.aggregate(
            total=Sum(F('quantite_voulue') * F('produit__prix_unitaire'))
        )['total'] or 0

        return super().changelist_view(request, extra_context=extra_context)
class FluxProduitInline(admin.TabularInline):
    model = FluxProduit
    extra = 1  # Permet d'ajouter une nouvelle étape de traçabilité en un clic
    readonly_fields = ('code_tracabilite', 'date_heure')    

@admin.register(Livraison)
class LivraisonAdmin(admin.ModelAdmin):
    # On affiche 'statut' et 'transporteur' dans list_display
    list_display = ('id', 'reservation', 'transporteur', 'statut', 'statut_couleur', 'date_depart')
    
    # On peut maintenant les rendre éditables
    list_editable = ('transporteur', 'statut')
    list_filter = ('statut', 'date_depart')
    inlines =[FluxProduitInline]


    def statut_couleur(self, obj):
        colors = {'livre': '#28a745', 'en_route': '#007bff', 'en_attente': '#ffc107'}
        color = colors.get(obj.statut, 'black')
        return format_html('<b style="color: {};">{}</b>', color, obj.get_statut_display())
    statut_couleur.short_description = 'Visuel État'
    def changelist_view(self, request, extra_context=None):
        from django.db.models import Sum, Count
        # On importe les modèles pour les calculs
        from .models import Livraison, Reservation

        extra_context = extra_context or {}

        # 1. On compte les statuts des camions (pour nb_total, nb_en_attente, etc.)
        extra_context['nb_total'] = Livraison.objects.count()
        extra_context['nb_en_attente'] = Livraison.objects.filter(statut='en_attente').count()
        extra_context['nb_en_route'] = Livraison.objects.filter(statut='en_route').count()
        extra_context['nb_livre'] = Livraison.objects.filter(statut='livre').count()

        # 2. On calcule les finances (pour total_commissions)
        # On utilise les cautions payées des réservations
        extra_context['total_commissions'] = Reservation.objects.filter(
            statut_caution='PAYE'
        ).aggregate(total=Sum('caution_20'))['total'] or 0

        # 3. Gains Nets (à 0 pour l'instant ou ton propre calcul)
        extra_context['total_gains_nets'] = 0

        return super().changelist_view(request, extra_context=extra_context)
@admin.register(Litige)
class LitigeAdmin(admin.ModelAdmin):
    list_display = ('livraison', 'declarant', 'date_creation', 'etat_litige')
    list_filter = ('resolu', 'date_creation')
    
    def etat_litige(self, obj):
        if obj.resolu:
            return mark_safe('<b style="color:green;">✅ RÉSOLU</b>')
        return mark_safe('<b style="color:red;">⚠️ EN ATTENTE</b>')
    etat_litige.short_description = "Statut du problème"    


@admin.register(AlerteSecuriteRoutiere)
class AlerteSecuriteRoutiereAdmin(admin.ModelAdmin):
    # CORRECTION : 'est_active' doit être présent ici pour pouvoir être édité en ligne
    list_display = ('axe_routier', 'badge_incident', 'description_danger', 'date_publication', 'est_active', 'badge_statut')
    
    # Le reste ne change pas
    list_filter = ('type_incident', 'est_active', 'date_publication')
    search_fields = ('axe_routier', 'description_danger')
    list_editable = ('est_active',)

    def badge_incident(self, obj):
        if obj.type_incident == 'BLOCAGE':
            return format_html('<span style="background-color: #ffc107; color: #000; padding: 5px 10px; border-radius: 12px; font-weight: bold; font-size: 11px;">⚠️ Barrage / Blocage</span>')
        elif obj.type_incident == 'TENSION':
            return format_html('<span style="background-color: #dc3545; color: #fff; padding: 5px 10px; border-radius: 12px; font-weight: bold; font-size: 11px;">🚨 Zone de Tension</span>')
        else:
            return format_html('<span style="background-color: #6c757d; color: #fff; padding: 5px 10px; border-radius: 12px; font-weight: bold; font-size: 11px;">🔧 Incident Route</span>')
    badge_incident.short_description = "Type d'incident"

    def badge_statut(self, obj):
        if obj.est_active:
            return format_html('<b style="color: #dc3545;">En cours</b>')
        return format_html('<b style="color: #28a745;">Résolu</b>')
    badge_statut.short_description = "Statut"
    

