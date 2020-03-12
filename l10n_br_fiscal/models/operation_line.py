# Copyright (C) 2019  Renato Lima - Akretion
# License AGPL-3 - See http://www.gnu.org/licenses/agpl-3.0.html

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..constants.fiscal import (
    FISCAL_IN_OUT_ALL,
    NFE_IND_IE_DEST,
    NFE_IND_IE_DEST_DEFAULT,
    OPERATION_STATE,
    OPERATION_STATE_DEFAULT,
    PRODUCT_FISCAL_TYPE,
    TAX_FRAMEWORK,
    TAX_FRAMEWORK_NORMAL,
    OPERATION_FISCAL_TYPE,
    CFOP_DESTINATION_EXPORT
)
from ..constants.icms import ICMS_ORIGIN


class OperationLine(models.Model):
    _name = "l10n_br_fiscal.operation.line"
    _description = "Fiscal Operation Line"
    _inherit = ["mail.thread"]

    operation_id = fields.Many2one(
        comodel_name="l10n_br_fiscal.operation",
        string="Operation",
        ondelete="cascade",
        required=True)

    name = fields.Char(
        string="Name",
        required=True)

    cfop_internal_id = fields.Many2one(
        comodel_name="l10n_br_fiscal.cfop",
        string="CFOP Internal",
        domain="[('type_in_out', '=', operation_type), "
               "('type_move', '=ilike', fiscal_type + '%'), "
               "('destination', '=', '1')]",
    )

    cfop_external_id = fields.Many2one(
        comodel_name="l10n_br_fiscal.cfop",
        string="CFOP External",
        domain="[('type_in_out', '=', operation_type), "
               "('type_move', '=ilike', fiscal_type + '%'), "
               "('destination', '=', '2')]",
    )

    cfop_export_id = fields.Many2one(
        comodel_name="l10n_br_fiscal.cfop",
        string="CFOP Export",
        domain="[('type_in_out', '=', operation_type), "
               "('type_move', '=ilike', fiscal_type + '%'), "
               "('destination', '=', '3')]",
    )

    operation_type = fields.Selection(
        selection=FISCAL_IN_OUT_ALL,
        related="operation_id.operation_type",
        string="Operation Type",
        store=True,
        readonly=True)

    fiscal_type = fields.Selection(
        selection=OPERATION_FISCAL_TYPE,
        related="operation_id.fiscal_type",
        string="Fiscal Type",
        store=True,
        readonly=True)

    line_inverse_id = fields.Many2one(
        comodel_name="l10n_br_fiscal.operation.line",
        string="Operation Line Inverse",
        domain="[('operation_type', '!=', operation_type)]",
        copy=False)

    line_refund_id = fields.Many2one(
        comodel_name="l10n_br_fiscal.operation.line",
        string="Operation Line Refund",
        domain="[('operation_type', '!=', operation_type)]",
        copy=False)

    partner_tax_framework = fields.Selection(
        selection=TAX_FRAMEWORK,
        string="Partner Tax Framework")

    ind_ie_dest = fields.Selection(
        selection=NFE_IND_IE_DEST,
        string="Contribuinte do ICMS",
        required=True,
        default=NFE_IND_IE_DEST_DEFAULT)

    product_type = fields.Selection(
        selection=PRODUCT_FISCAL_TYPE,
        string="Product Fiscal Type")

    company_tax_framework = fields.Selection(
        selection=TAX_FRAMEWORK,
        string="Copmpany Tax Framework")

    add_to_amount = fields.Boolean(
        string="Add to Document Amount?",
        default=True)

    icms_origin = fields.Selection(
        selection=ICMS_ORIGIN,
        string="Origin",
        default="0")

    tax_definition_ids = fields.One2many(
        comodel_name="l10n_br_fiscal.tax.definition",
        inverse_name="operation_line_id",
        string="Tax Definition")

    comment_ids = fields.Many2many(
        comodel_name="l10n_br_fiscal.comment",
        relation="l10n_br_fiscal_operation_line_comment_rel",
        column1="operation_id",
        column2="comment_id",
        string="Comment")

    state = fields.Selection(
        selection=OPERATION_STATE,
        string="State",
        default=OPERATION_STATE_DEFAULT,
        index=True,
        readonly=True,
        track_visibility="onchange",
        copy=False)

    _sql_constraints = [(
        "fiscal_operation_name_uniq",
        "unique (name, operation_id)",
        _("Fiscal Operation Line already exists with this name !"))]

    def _get_cfop(self, company, partner):
        cfop = False
        if partner.state_id == company.state_id:
            cfop = self.cfop_internal_id
        if partner.state_id != company.state_id:
            cfop = self.cfop_external_id
        if partner.country_id != company.country_id:
            cfop = self.cfop_export_id
        return cfop

    def map_fiscal_taxes(self, company, partner, product=None,
                         fiscal_price=None, fiscal_quantity=None,
                         ncm=None, nbs=None, cest=None):

        mapping_result = {
            'taxes': {},
            'cfop': False,
            'taxes_value': 0.00
        }

        self.ensure_one()

        # Define CFOP
        cfop = self._get_cfop(company, partner)
        mapping_result['cfop'] = cfop

        # 1 Get Tax Defs from Company
        for tax in company.tax_definition_ids.mapped('tax_id'):
            mapping_result['taxes'][tax.tax_domain] = tax

        # 2 From NCM
        if not ncm and product:
            ncm = product.ncm_id

        if company.tax_framework == TAX_FRAMEWORK_NORMAL:
            tax_ipi = ncm.tax_ipi_id
            tax_ii = ncm.tax_ii_id
            mapping_result['taxes'][tax_ipi.tax_domain] = tax_ipi

            if mapping_result['cfop'].destination == CFOP_DESTINATION_EXPORT:
                mapping_result['taxes'][tax_ii.tax_domain] = tax_ii

            # 3 From ICMS Regulation
            tax_icms_ids = company.icms_regulation_id.map_tax_icms(
                company=company,
                partner=partner,
                product=product,
                ncm=ncm,
                cest=cest)

            for tax in tax_icms_ids:
                mapping_result['taxes'][tax.tax_domain] = tax

            # 4 From Operation Line
            for tax in self.tax_definition_ids.mapped('tax_id'):
                mapping_result['taxes'][tax.tax_domain] = tax

            # 5 From CFOP
            for tax in cfop.tax_definition_ids.mapped('tax_id'):
                mapping_result['taxes'][tax.tax_domain] = tax

            # 6 From Partner Profile
            for tax in partner.fiscal_profile_id.tax_definition_ids.mapped('tax_id'):
                mapping_result['taxes'][tax.tax_domain] = tax

        return mapping_result

    @api.multi
    def action_review(self):
        self.write({"state": "review"})

    @api.multi
    def unlink(self):
        lines = self.filtered(lambda l: l.state == "approved")
        if lines:
            raise UserError(
                _("You cannot delete an Operation Line which is not draft !")
            )
        return super(OperationLine, self).unlink()

    @api.multi
    @api.onchange("operation_id")
    def _onchange_operation_id(self):
        if not self.operation_id.operation_type:
            warning = {
                "title": _("Warning!"),
                "message": _("You must first select a operation type."),
            }
            return {"warning": warning}
